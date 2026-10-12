"""WeChat file synchronization against temporary capture and storage only."""

import contextlib
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape

from app.extensions import db
from app.models import FileNode, Project, ProjectMember, ProjectSettings, StorageObject, User
from app.readable_storage import register_readable_storage
from app.storage import resolve_object_path
from app.wechat_files import (
    CaptureFiles, WeChatFileImport, WeChatFileSyncState, _copy_one, _project,
    parse_attachment, register_wechat_files, sync_wechat_files,
)
import test_project_storage as fixtures


class WeChatFileTests(unittest.TestCase):
    DC_USER = fixtures.ProjectStorageTests.DC_USER
    MEMBER = fixtures.ProjectStorageTests.MEMBER
    OTHER_ADMIN = fixtures.ProjectStorageTests.OTHER_ADMIN
    OWNER = fixtures.ProjectStorageTests.OWNER
    SPECIAL = fixtures.ProjectStorageTests.SPECIAL
    ORDINARY = fixtures.ProjectStorageTests.ORDINARY
    OWNED_SPECIAL = fixtures.ProjectStorageTests.OWNED_SPECIAL
    OTHER_ADMIN_PROJECT = fixtures.ProjectStorageTests.OTHER_ADMIN_PROJECT
    headers = fixtures.ProjectStorageTests.headers
    assert_ok = fixtures.ProjectStorageTests.assert_ok
    upload = fixtures.ProjectStorageTests.upload
    storage = fixtures.ProjectStorageTests.storage
    tearDown = fixtures.ProjectStorageTests.tearDown

    def setUp(self):
        fixtures.ProjectStorageTests.setUp(self)
        self.capture = self.base / "capture.sqlite"
        self.source = self.base / "wechat/msg/file"
        self.media = self.base / "capture/media"
        self.source.mkdir(parents=True)
        self.media.mkdir(parents=True)
        with self.capture_db() as source:
            source.execute("CREATE TABLE messages(message_uid TEXT PRIMARY KEY,chat_username TEXT,chat_display_name TEXT,create_time INTEGER,base_type INTEGER,message_content TEXT,source_message_db TEXT)")
            source.execute("CREATE TABLE message_media(message_uid TEXT PRIMARY KEY,media_path TEXT,mime_type TEXT,status TEXT)")
        self.app.config.update(
            WECHAT_FILES_ENABLED=True, WECHAT_FILES_CAPTURE_DB=str(self.capture),
            WECHAT_FILES_SOURCE_ROOT=str(self.source), WECHAT_FILES_MEDIA_ROOT=str(self.media),
            READABLE_STORAGE_ENABLED=True, READABLE_HISTORY_ROOT=str(self.base / "history"),
            MESSAGE_BRIDGE_ENABLED=False,
        )
        register_readable_storage(self.app)
        register_wechat_files(self.app)

    @contextlib.contextmanager
    def capture_db(self):
        with contextlib.closing(sqlite3.connect(self.capture)) as connection:
            with connection:
                yield connection

    def test_wechat_project_uses_configured_storage_owner(self):
        self.app.config["SPECIAL_STORAGE_USERNAME"] = "configured_storage_owner"
        with self.assertRaisesRegex(ValueError, "configured storage"):
            _project()
        owner = db.session.get(User, self.DC_USER)
        owner.username = "configured_storage_owner"
        db.session.commit()
        project_id, _, owner_id = _project()
        self.assertEqual(owner_id, self.DC_USER)
        self.assertEqual(db.session.get(Project, project_id).creator_id, self.DC_USER)

    def attachment(self, uid, name="课程说明.pdf", content=b"raw original attachment", chat="class@chatroom", downloaded=True, md5=True):
        digest = hashlib.md5(content).hexdigest() if md5 else ""
        body = f"<msg><appmsg><type>6</type><title>{escape(name)}</title><md5>{digest}</md5><appattach><totallen>{len(content)}</totallen><fileext>pdf</fileext></appattach></appmsg></msg>"
        with self.capture_db() as source:
            source.execute("INSERT OR REPLACE INTO messages VALUES(?,?,?,?,?,?,?)", (uid, chat, "课程群", 1791720000, 49, body, "decrypted/message.db"))
        path = self.source / ("download-" + uid.replace(":", "_") + ".bin" if md5 else name)
        if downloaded:
            path.write_bytes(content)
        return path

    def media_item(self, uid, status="ready", content=b"RIFFdecoded voice", mime="audio/wav", path=None):
        target = self.media / (uid + ".wav")
        target.write_bytes(content)
        with self.capture_db() as source:
            source.execute("INSERT OR REPLACE INTO messages VALUES(?,?,?,?,?,?,?)", (uid, "voice@chatroom", "语音群", 1791720000, 34, "voice metadata", "decrypted/message.db"))
            source.execute("INSERT OR REPLACE INTO message_media VALUES(?,?,?,?)", (uid, str(path or target), mime, status))
        return target

    def imported(self, uid):
        row = WeChatFileImport.query.filter_by(message_uid=uid).one()
        node = db.session.get(FileNode, row.file_node_id) if row.file_node_id else None
        stored = db.session.get(StorageObject, node.storage_object_id) if node else None
        path = Path(resolve_object_path(stored.storage_rel_path)) if stored else None
        return row, node, stored, path

    def test_named_raw_copies_uid_idempotence_and_original_projects_unchanged(self):
        ordinary = self.upload(self.ORDINARY, self.MEMBER, b"ordinary unchanged", name="existing.txt")
        ordinary_stored = self.storage(ordinary["id"])
        before = (ordinary_stored.id, ordinary_stored.storage_rel_path, Path(resolve_object_path(ordinary_stored.storage_rel_path)).read_bytes())
        contents = {"first": b"first original bytes", "second": b"second original bytes", "third": b"third original bytes"}
        sources = [self.attachment("first", content=contents["first"]), self.attachment("second", content=contents["second"], chat="another@chatroom"), self.attachment("third", content=contents["third"])]
        before_source = [(path.read_bytes(), path.stat().st_mtime_ns) for path in sources]
        capture_hash = hashlib.sha256(self.capture.read_bytes()).hexdigest()
        result = sync_wechat_files()
        self.assertEqual(result["imported"], 3)
        project = db.session.get(Project, result["project_id"])
        self.assertEqual((project.name, project.creator_id), ("微信文件", self.DC_USER))
        self.assertFalse(ProjectSettings.query.filter_by(project_id=project.id).one().guest_visible)
        self.assertEqual([(row.user_id, row.role_project) for row in ProjectMember.query.filter_by(project_id=project.id)], [(self.DC_USER, "creator")])
        paths = []
        for uid in ("first", "second", "third"):
            row, node, stored, path = self.imported(uid)
            self.assertEqual(path.read_bytes(), contents[uid])
            self.assertEqual(stored.sha256, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertTrue(path.is_relative_to(self.dc_root.resolve()))
            self.assertIn("2026-10", path.parts)
            self.assertEqual(path.suffix, ".pdf")
            self.assertEqual(node.name, "课程说明.pdf")
            paths.append(path)
        self.assertEqual(len(set(paths)), 3)
        self.assertNotEqual(paths[0].parent.parent, paths[1].parent.parent)
        self.assertEqual([(path.read_bytes(), path.stat().st_mtime_ns) for path in sources], before_source)
        self.assertEqual(hashlib.sha256(self.capture.read_bytes()).hexdigest(), capture_hash)
        self.assertEqual(sync_wechat_files()["unchanged"], 3)
        self.assertEqual(WeChatFileSyncState.query.count(), 1)
        self.assertEqual(WeChatFileImport.query.count(), 3)
        self.assertEqual(Project.query.count(), 5)
        self.assertEqual((ordinary_stored.id, ordinary_stored.storage_rel_path, Path(resolve_object_path(ordinary_stored.storage_rel_path)).read_bytes()), before)
        self.assertFalse(list(self.dc_root.rglob("*.bin")))

    def test_private_project_uses_current_membership_for_list_and_download(self):
        self.attachment("private")
        project_id = sync_wechat_files()["project_id"]
        _, node, _, _ = self.imported("private")
        self.assertEqual(self.client.get(f"/api/projects/{project_id}", headers=self.headers(self.MEMBER)).status_code, 403)
        self.assertEqual(self.client.get(f"/api/files/root?scope=project&project_id={project_id}", headers=self.headers(self.MEMBER)).status_code, 403)
        self.assertEqual(self.client.get(f"/api/files/{node.id}/download", headers=self.headers(self.MEMBER)).status_code, 403)
        response = self.client.get(f"/api/files/{node.id}/download", headers=self.headers(self.DC_USER))
        self.assertEqual(response.data, b"raw original attachment")
        response.close()
        db.session.add(ProjectMember(project_id=project_id, user_id=self.MEMBER, role_project="user"))
        db.session.commit()
        response = self.client.get(f"/api/files/{node.id}/download", headers=self.headers(self.MEMBER))
        self.assertEqual(response.status_code, 200)
        response.close()
        ProjectMember.query.filter_by(project_id=project_id, user_id=self.MEMBER).delete()
        db.session.commit()
        self.assertEqual(self.client.get(f"/api/files/{node.id}/download", headers=self.headers(self.MEMBER)).status_code, 403)

    def test_late_download_and_ready_decoded_media_retry_without_encrypted_imports(self):
        missing = self.attachment("late", downloaded=False)
        self.media_item("voice")
        self.media_item("encrypted", status="missing_key", content=b"encrypted data", mime="image/jpeg")
        result = sync_wechat_files()
        self.assertEqual(result["imported"], 1)
        self.assertEqual(self.imported("late")[0].status, "missing_file")
        self.assertEqual(self.imported("encrypted")[0].status, "not_ready")
        self.assertEqual(self.imported("voice")[3].read_bytes(), b"RIFFdecoded voice")
        self.assertEqual(self.imported("voice")[3].suffix, ".wav")
        missing.write_bytes(b"raw original attachment")
        result = sync_wechat_files()
        self.assertEqual(result["imported"], 1)
        self.assertEqual(self.imported("late")[3].read_bytes(), b"raw original attachment")
        self.assertEqual(len([path for path in self.dc_root.rglob("*") if path.is_file()]), 2)

    def test_changed_source_keeps_file_uid_and_user_name_then_missing_retains_copy(self):
        source = self.attachment("update", content=b"old bytes")
        sync_wechat_files()
        record, node, _, path = self.imported("update")
        node_id = node.id
        self.assert_ok(self.client.patch(f"/api/files/{node_id}", json={"name": "我的说明.pdf"}, headers=self.headers(self.DC_USER)))
        self.attachment("update", content=b"new updated bytes")
        # A source rewrite must not mutate the already imported target before
        # the next synchronization transaction commits.
        self.assertEqual(self.imported("update")[3].read_bytes(), b"old bytes")
        self.assertEqual(sync_wechat_files()["updated"], 1)
        record, node, stored, path = self.imported("update")
        self.assertEqual(node.id, node_id)
        self.assertEqual(path.name, "我的说明.pdf")
        self.assertEqual(path.read_bytes(), b"new updated bytes")
        source.unlink()
        self.assertEqual(sync_wechat_files()["missing_file"], 1)
        self.assertEqual(path.read_bytes(), b"new updated bytes")
        with self.capture_db() as capture:
            capture.execute("DELETE FROM messages WHERE message_uid='update'")
        sync_wechat_files()
        self.assertEqual(self.imported("update")[0].status, "source_removed")
        self.assertEqual(path.read_bytes(), b"new updated bytes")

    def test_owner_delete_is_not_resurrected_by_timer(self):
        self.attachment("deleted")
        sync_wechat_files()
        _, node, _, path = self.imported("deleted")
        self.assert_ok(self.client.delete(f"/api/files/{node.id}", headers=self.headers(self.DC_USER)))
        self.assertFalse(path.exists())
        self.assertEqual(sync_wechat_files()["owner_deleted"], 1)
        row = WeChatFileImport.query.filter_by(message_uid="deleted").one()
        self.assertEqual(row.status, "owner_deleted")
        self.assertFalse(FileNode.query.filter_by(id=row.file_node_id, deleted_at=None).first())

    def test_changed_xml_md5_cannot_reuse_cached_matching_path(self):
        self.attachment("metadata", content=b"AAAA")
        sync_wechat_files()
        (self.source / "another-download.bin").write_bytes(b"BBBB")
        new_md5 = hashlib.md5(b"BBBB").hexdigest()
        body = f"<appmsg><type>6</type><title>纠正名称.pdf</title><md5>{new_md5}</md5><appattach><totallen>4</totallen></appattach></appmsg>"
        with self.capture_db() as source:
            source.execute("UPDATE messages SET message_content=? WHERE message_uid='metadata'", (body,))
        self.assertEqual(sync_wechat_files()["updated"], 1)
        record, node, _, path = self.imported("metadata")
        self.assertEqual(record.source_md5, new_md5)
        self.assertEqual(path.read_bytes(), b"BBBB")
        self.assertEqual((node.name, path.name), ("纠正名称.pdf", "纠正名称.pdf"))

    def test_md5_mismatch_and_ambiguous_name_never_import_wrong_bytes(self):
        path = self.attachment("wrong", content=b"valid bytes")
        path.write_bytes(b"other bytes")
        self.attachment("ambiguous", name="same.pdf", md5=False)
        duplicate = self.source / "another/same.pdf"
        duplicate.parent.mkdir()
        duplicate.write_bytes(b"raw original attachment")
        result = sync_wechat_files()
        self.assertEqual(result["imported"], 3)
        self.assertEqual(self.imported("wrong")[0].status, "missing_file")
        self.assertEqual(self.imported("ambiguous")[0].status, "ambiguous_file")
        self.assertIsNone(self.imported("wrong")[1])
        self.assertIsNone(self.imported("ambiguous")[1])
        # Real downloads remain available in the private unassociated folder;
        # they are never mislabeled as a verified message attachment.
        self.assertEqual(WeChatFileImport.query.filter_by(source_kind="unlinked").count(), 3)

    def test_symlinks_media_traversal_and_virtual_messages_are_excluded(self):
        secret = self.base / "secret.wav"
        secret.write_bytes(b"private outside media")
        self.media_item("escape", path=secret)
        self.media_item("relative-escape", path="../secret.wav")
        self.attachment("netdisk:instance:inbox:1", chat="netdisk:instance:thread:1", downloaded=False)
        symlink = self.source / "linked.bin"
        try:
            symlink.symlink_to(secret)
        except OSError:
            symlink = None
        result = sync_wechat_files()
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["scanned"], 2)
        self.assertEqual(WeChatFileImport.query.count(), 2)
        self.assertEqual(secret.read_bytes(), b"private outside media")
        if symlink:
            self.assertNotIn(symlink, [path for values in CaptureFiles().files_by_size.values() for path in values])

    def test_limit_is_resumable_and_does_not_skip_older_late_files(self):
        self.attachment("old-late", downloaded=False)
        for uid in ("a", "b", "c"):
            self.attachment(uid, content=uid.encode())
        result = sync_wechat_files(limit=2)
        self.assertEqual((result["imported"], result["deferred"]), (2, 1))
        result = sync_wechat_files(limit=2)
        self.assertEqual((result["imported"], result["unchanged"]), (1, 2))
        (self.source / "download-old-late.bin").write_bytes(b"raw original attachment")
        self.assertEqual(sync_wechat_files(limit=2)["imported"], 1)
        self.assertEqual(WeChatFileImport.query.filter(WeChatFileImport.file_node_id.isnot(None)).count(), 4)

    def test_unindexed_download_is_copied_and_late_message_moves_same_node(self):
        source = self.source / "离线下载.pdf"
        source.write_bytes(b"unindexed original bytes")
        result = sync_wechat_files()
        self.assertEqual(result["imported"], 1)
        orphan_uid = "wechat-download:离线下载.pdf"
        record, node, _, original_target = self.imported(orphan_uid)
        node_id = node.id
        self.assertIn("未关联会话", original_target.parts)
        self.assertEqual(original_target.name, "离线下载.pdf")
        self.assertEqual(original_target.read_bytes(), source.read_bytes())
        # Add only the message metadata: the pre-existing physical download is
        # the exact same source, not a second file supplied by the fixture.
        self.attachment("late-metadata", name="原始聊天附件.pdf", content=source.read_bytes(), downloaded=False)
        result = sync_wechat_files()
        self.assertEqual(result["imported"], 0)
        linked, real_node, _, moved = self.imported("late-metadata")
        self.assertEqual(real_node.id, node_id)
        self.assertNotIn("未关联会话", moved.parts)
        self.assertEqual(moved.name, "原始聊天附件.pdf")
        self.assertFalse(original_target.exists())
        self.assertEqual(WeChatFileImport.query.filter_by(message_uid=orphan_uid).one().status, "linked")
        self.assertEqual(len([path for path in self.dc_root.rglob("*") if path.is_file()]), 1)
        self.assertEqual(sync_wechat_files()["unchanged"], 1)

    def test_orphan_ready_waveform_uses_only_media_index_and_reconciles_late_capture(self):
        wave = self.media / "orphan.wav"
        wave.write_bytes(b"RIFF orphan decoded voice")
        (self.media / "index.json").write_text("private media worker index")
        (self.media / "unindexed.wav").write_bytes(b"unindexed waveform is excluded")
        with self.capture_db() as capture:
            capture.execute("INSERT INTO message_media VALUES(?,?,?,?)", ("orphan-voice", str(wave), "audio/wav", "ready"))
            capture.execute("INSERT INTO message_media VALUES(?,?,?,?)", ("netdisk:virtual-media", str(wave), "audio/wav", "ready"))
        self.assertEqual(sync_wechat_files()["imported"], 1)
        record, node, _, target = self.imported("orphan-voice")
        node_id = node.id
        self.assertEqual(record.source_kind, "media_orphan")
        self.assertIn("未关联会话", target.parts)
        self.assertEqual(target.read_bytes(), wave.read_bytes())
        with self.capture_db() as capture:
            capture.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?)", ("orphan-voice", "real-voice-chat", "真实语音会话", 1791720000, 34, "voice metadata", "decrypted/message.db"))
        result = sync_wechat_files()
        self.assertEqual(result["imported"], 0)
        record, node, _, moved = self.imported("orphan-voice")
        self.assertEqual((node.id, record.source_kind), (node_id, "media"))
        self.assertNotIn("未关联会话", moved.parts)
        self.assertFalse(target.exists())
        self.assertEqual(len([path for path in self.dc_root.rglob("*") if path.is_file()]), 1)

    def test_missing_metadata_does_not_duplicate_linked_download_or_restore_owner_delete(self):
        path = self.source / "standalone.pdf"
        path.write_bytes(b"linked bytes")
        sync_wechat_files()
        self.attachment("linked-message", content=b"linked bytes", downloaded=False)
        sync_wechat_files()
        _, node, _, target = self.imported("linked-message")
        with self.capture_db() as source:
            source.execute("DELETE FROM messages WHERE message_uid='linked-message'")
        self.assertEqual(sync_wechat_files()["unchanged"], 1)
        self.assertEqual(len([path for path in self.dc_root.rglob("*") if path.is_file()]), 1)
        self.assertEqual(target.read_bytes(), b"linked bytes")
        self.assert_ok(self.client.delete(f"/api/files/{node.id}", headers=self.headers(self.DC_USER)))
        self.assertEqual(sync_wechat_files()["owner_deleted"], 1)
        self.assertFalse([path for path in self.dc_root.rglob("*") if path.is_file()])

    def test_ready_media_index_covers_unfamiliar_types_nonfile_appmsg_and_null_chat(self):
        for uid in ("unfamiliar-type", "null-type", "nonfile-appmsg", "null-chat", "unready-unknown"):
            self.media_item(uid, status="missing_key" if uid == "unready-unknown" else "ready")
        with self.capture_db() as capture:
            capture.execute("UPDATE messages SET base_type=1 WHERE message_uid IN ('unfamiliar-type','unready-unknown')")
            capture.execute("UPDATE messages SET base_type=NULL WHERE message_uid='null-type'")
            capture.execute("UPDATE messages SET base_type=49,message_content='<appmsg><type>5</type></appmsg>' WHERE message_uid='nonfile-appmsg'")
            capture.execute("UPDATE messages SET chat_username=NULL WHERE message_uid='null-chat'")
        result = sync_wechat_files()
        self.assertEqual((result["imported"], result["failed"]), (4, 0))
        ids = []
        for uid in ("unfamiliar-type", "null-type", "nonfile-appmsg", "null-chat"):
            record, node, _, target = self.imported(uid)
            self.assertEqual(target.read_bytes(), b"RIFFdecoded voice")
            self.assertEqual(target.suffix, ".wav")
            self.assertTrue(target.name.startswith("语音 "))
            self.assertEqual(record.source_kind, "media_orphan" if uid == "null-chat" else "media")
            self.assertEqual("未关联会话" in target.parts, uid == "null-chat")
            ids.append(node.id)
        self.assertIsNone(WeChatFileImport.query.filter_by(message_uid="unready-unknown").first())
        self.assertEqual(sync_wechat_files()["unchanged"], 4)
        self.assertEqual([self.imported(uid)[1].id for uid in ("unfamiliar-type", "null-type", "nonfile-appmsg", "null-chat")], ids)
        _, original_node, _, original_path = self.imported("null-chat")
        with self.capture_db() as capture:
            capture.execute("UPDATE messages SET chat_username='late-real-chat',chat_display_name='恢复的会话' WHERE message_uid='null-chat'")
        result = sync_wechat_files()
        record, node, _, moved = self.imported("null-chat")
        self.assertEqual(result.get("imported", 0), 0)
        self.assertEqual((node.id, record.source_kind), (original_node.id, "media"))
        self.assertNotIn("未关联会话", moved.parts)
        self.assertFalse(original_path.exists())

    def test_null_attachment_chat_copies_safely_and_late_chat_moves_same_node(self):
        self.attachment("null-attachment-chat", chat=None)
        self.assertEqual(sync_wechat_files()["imported"], 1)
        record, node, _, original = self.imported("null-attachment-chat")
        node_id = node.id
        self.assertEqual(record.source_kind, "attachment")
        self.assertIn("未关联会话", original.parts)
        self.assertEqual(original.read_bytes(), b"raw original attachment")
        self.assertEqual(sync_wechat_files()["unchanged"], 1)
        with self.capture_db() as capture:
            capture.execute("UPDATE messages SET chat_username='real-attachment-chat' WHERE message_uid='null-attachment-chat'")
        self.assertEqual(sync_wechat_files()["unchanged"], 1)
        record, node, _, moved = self.imported("null-attachment-chat")
        self.assertEqual(node.id, node_id)
        self.assertNotIn("未关联会话", moved.parts)
        self.assertFalse(original.exists())
        self.assertEqual(len([path for path in self.dc_root.rglob("*") if path.is_file()]), 1)

    def test_deferred_unlinked_identity_becomes_alias_when_message_arrives_first(self):
        self.attachment("fills-limit", content=b"one indexed document")
        source = self.source / "deferred.pdf"
        source.write_bytes(b"deferred document")
        self.assertEqual(sync_wechat_files(limit=1)["deferred"], 1)
        pending = WeChatFileImport.query.filter_by(message_uid="wechat-download:deferred.pdf").one()
        self.assertIsNone(pending.file_node_id)
        self.attachment("metadata-before-copy", content=source.read_bytes(), downloaded=False)
        self.assertEqual(sync_wechat_files()["imported"], 1)
        real = WeChatFileImport.query.filter_by(message_uid="metadata-before-copy").one()
        alias = WeChatFileImport.query.filter_by(message_uid="wechat-download:deferred.pdf").one()
        self.assertEqual((alias.file_node_id, alias.status), (real.file_node_id, "linked"))
        with self.capture_db() as capture:
            capture.execute("DELETE FROM messages WHERE message_uid='metadata-before-copy'")
        result = sync_wechat_files()
        self.assertEqual(result["imported"], 0)
        self.assertEqual(len([path for path in self.dc_root.rglob("*") if path.is_file()]), 2)

    def test_replaced_unlinked_download_keeps_old_verified_chat_copy(self):
        source = self.source / "reused.pdf"
        source.write_bytes(b"old original")
        sync_wechat_files()
        self.attachment("original-message", content=b"old original", downloaded=False)
        sync_wechat_files()
        _, original_node, _, original_target = self.imported("original-message")
        source.write_bytes(b"new unrelated download")
        result = sync_wechat_files()
        self.assertEqual(result["imported"], 1)
        self.assertEqual(original_target.read_bytes(), b"old original")
        alias, replacement_node, _, replacement = self.imported("wechat-download:reused.pdf")
        self.assertNotEqual(replacement_node.id, original_node.id)
        self.assertIn("未关联会话", replacement.parts)
        self.assertEqual(replacement.read_bytes(), b"new unrelated download")
        self.assertEqual(len([path for path in self.dc_root.rglob("*") if path.is_file()]), 2)

    def test_failed_database_commit_restores_previous_file_and_cleans_staging(self):
        self.attachment("rollback", content=b"before")
        sync_wechat_files()
        _, node, stored, target = self.imported("rollback")
        original_id = stored.id
        self.attachment("rollback", content=b"after changed")
        reader = CaptureFiles()
        item = next(reader.messages())
        project_id, root_id, owner_id = _project()
        with patch.object(db.engine.dialect, "do_commit", side_effect=RuntimeError("simulated durable commit failure")):
            with self.assertRaises(RuntimeError):
                _copy_one(reader, item, project_id, root_id, owner_id)
        db.session.remove()
        self.assertEqual(target.read_bytes(), b"before")
        self.assertEqual(self.imported("rollback")[2].id, original_id)
        incoming = self.base / "history/.incoming"
        self.assertFalse([path for path in incoming.rglob("*") if path.is_file()])
        self.assertEqual(sync_wechat_files()["updated"], 1)
        self.assertEqual(target.read_bytes(), b"after changed")

    def test_project_key_collision_and_disabled_owner_fail_without_reusing_projects(self):
        self.attachment("blocked")
        conflicting = db.session.get(Project, self.ORDINARY)
        conflicting.key = "WECHAT_FILES"
        db.session.commit()
        with self.assertRaisesRegex(ValueError, "already used"):
            sync_wechat_files()
        db.session.rollback()
        self.assertEqual(WeChatFileSyncState.query.count(), 0)
        self.assertEqual(conflicting.creator_id, self.OWNER)
        conflicting.key = "NORMAL"
        db.session.get(User, self.DC_USER).role_system = "user"
        db.session.commit()
        with self.assertRaisesRegex(ValueError, "super administrator"):
            sync_wechat_files()
        db.session.rollback()
        self.assertEqual(WeChatFileImport.query.count(), 0)

    def test_cli_disabled_and_success_only_print_aggregate_metadata(self):
        self.attachment("cli")
        self.app.config["WECHAT_FILES_ENABLED"] = False
        runner = self.app.test_cli_runner()
        disabled = runner.invoke(args=["sync-wechat-files"])
        self.assertNotEqual(disabled.exit_code, 0)
        self.assertEqual(WeChatFileSyncState.query.count(), 0)
        self.app.config["WECHAT_FILES_ENABLED"] = True
        complete = runner.invoke(args=["sync-wechat-files", "--limit", "0"])
        self.assertEqual(complete.exit_code, 0, complete.output)
        self.assertEqual(json.loads(complete.output)["imported"], 1)
        for private in ("课程说明", "class@chatroom", str(self.source)):
            self.assertNotIn(private, complete.output)

    def test_xml_entity_payload_and_invalid_sizes_cannot_select_arbitrary_files(self):
        self.assertIsNone(parse_attachment('<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///private">]><appmsg><type>6</type></appmsg>'))
        self.assertIsNone(parse_attachment('<appmsg><type>6</type><appattach><totallen>-1</totallen></appattach></appmsg>'))
        self.assertIsNone(parse_attachment('<appmsg><type>6</type><md5>bad</md5><appattach><totallen>1</totallen></appattach></appmsg>'))
        metadata = parse_attachment('sender:\n&lt;appmsg&gt;&lt;type&gt;6&lt;/type&gt;&lt;title&gt;test.pdf&lt;/title&gt;&lt;appattach&gt;&lt;totallen&gt;1&lt;/totallen&gt;&lt;/appattach&gt;&lt;/appmsg&gt;')
        self.assertEqual(metadata, {"name": "test.pdf", "size": 1, "md5": ""})


if __name__ == "__main__":
    unittest.main()
