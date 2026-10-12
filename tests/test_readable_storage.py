"""Readable project-tree regressions using temporary storage and SQLite only."""

import io
import contextlib
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
import zipfile

from sqlalchemy import event, update
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import FileNode, Project, StorageObject, utcnow
from app.readable_storage import register_readable_storage, sync_project
from app.storage import resolve_object_path
from test_project_storage import InlineThread
import test_project_storage as storage_fixture


class ReadableStorageTests(unittest.TestCase):
    DC_USER=storage_fixture.ProjectStorageTests.DC_USER
    MEMBER=storage_fixture.ProjectStorageTests.MEMBER
    OTHER_ADMIN=storage_fixture.ProjectStorageTests.OTHER_ADMIN
    OWNER=storage_fixture.ProjectStorageTests.OWNER
    SPECIAL=storage_fixture.ProjectStorageTests.SPECIAL
    ORDINARY=storage_fixture.ProjectStorageTests.ORDINARY
    OWNED_SPECIAL=storage_fixture.ProjectStorageTests.OWNED_SPECIAL
    OTHER_ADMIN_PROJECT=storage_fixture.ProjectStorageTests.OTHER_ADMIN_PROJECT
    headers=storage_fixture.ProjectStorageTests.headers
    assert_ok=storage_fixture.ProjectStorageTests.assert_ok
    upload=storage_fixture.ProjectStorageTests.upload
    storage=storage_fixture.ProjectStorageTests.storage
    link=storage_fixture.ProjectStorageTests.link
    tearDown=storage_fixture.ProjectStorageTests.tearDown

    def setUp(self):
        storage_fixture.ProjectStorageTests.setUp(self)
        self.app.config.update(READABLE_STORAGE_ENABLED=True,READABLE_HISTORY_ROOT=str(self.base/"history"),MESSAGE_BRIDGE_ENABLED=False)
        register_readable_storage(self.app)

    def folder(self,name,parent=None):
        response=self.client.post("/api/files/folders",json={
            "scope":"project","project_id":self.SPECIAL,
            "parent_id":parent or self.roots[self.SPECIAL],"name":name,
        },headers=self.headers(self.MEMBER))
        result=self.assert_ok(response)
        return result.get("folder") or result.get("node")

    def upload_in(self,parent,name="课程说明.txt",content=b"plain readable contents"):
        response=self.client.post("/api/files/upload",data={
            "scope":"project","project_id":str(self.SPECIAL),"parent_id":str(parent),
            "file":(io.BytesIO(content),name,"text/plain"),
        },headers=self.headers(self.MEMBER))
        return self.assert_ok(response)["file"]

    def readable(self,file_id,content,basename=None):
        stored=self.storage(file_id)
        self.assertIn(f"_special_storage/projects/{self.SPECIAL}/tree/",stored.storage_rel_path)
        path=Path(resolve_object_path(stored.storage_rel_path))
        self.assertTrue(path.is_relative_to(self.dc_root.resolve()))
        self.assertEqual(path.read_bytes(),content)
        if basename is not None:
            self.assertEqual(path.name,basename)
        return stored,path

    def assert_only_named_tree(self, files):
        self.assertEqual({path for path in self.dc_root.rglob("*") if path.is_file()},set(files))
        expected_roots={self.dc_root/path.relative_to(self.dc_root).parts[0] for path in files}
        self.assertEqual(set(self.dc_root.iterdir()),expected_roots)
        self.assertFalse((self.dc_root/"projects").exists())

    def test_direct_and_chunk_upload_materialize_original_names_and_plain_bytes(self):
        node=self.upload(self.SPECIAL,self.MEMBER,b"direct bytes",name="测试文档.txt")
        _,direct_path=self.readable(node["id"],b"direct bytes","测试文档.txt")
        self.assert_only_named_tree([direct_path])
        self.assertTrue((self.base/"history"/".incoming"/"projects"/str(self.SPECIAL)/"objects").is_dir())
        payload=b"chunked bytes"
        response=self.client.post("/api/files/upload-sessions",json={
            "scope":"project","project_id":self.SPECIAL,"parent_id":self.roots[self.SPECIAL],
            "filename":"分片文档.txt","size":len(payload),"chunk_size":4,"mime_type":"text/plain",
        },headers=self.headers(self.MEMBER))
        upload_id=self.assert_ok(response)["session"]["upload_id"]
        for index,offset in enumerate(range(0,len(payload),4)):
            self.assert_ok(self.client.put(f"/api/files/upload-sessions/{upload_id}/chunks/{index}",data=payload[offset:offset+4],headers=self.headers(self.MEMBER)))
        response=self.client.post(f"/api/files/upload-sessions/{upload_id}/complete",headers=self.headers(self.MEMBER))
        chunked=self.assert_ok(response)["file"]
        _,chunked_path=self.readable(chunked["id"],payload,"分片文档.txt")
        self.assert_only_named_tree([direct_path,chunked_path])
        self.assertFalse([path for path in self.dc_root.rglob("*") if path.is_file() and path.suffix in (".zip",".pending")])

    def test_file_folder_project_renames_and_move_follow_physical_paths(self):
        first=self.folder("资料一")
        second=self.folder("资料二")
        content=b"move me"
        node=self.upload_in(first["id"],"说明.txt",content)
        _,old_path=self.readable(node["id"],content)
        self.assert_ok(self.client.patch(f"/api/files/{node['id']}",json={"name":"新说明.txt"},headers=self.headers(self.MEMBER)))
        _,path=self.readable(node["id"],content,"新说明.txt")
        self.assertFalse(old_path.exists())
        old_path=path
        self.assert_ok(self.client.patch(f"/api/files/{first['id']}",json={"name":"资料改名"},headers=self.headers(self.MEMBER)))
        _,path=self.readable(node["id"],content)
        self.assertIn("资料改名",path.parts)
        self.assertFalse(old_path.exists())
        old_path=path
        self.assert_ok(self.client.patch(f"/api/files/{node['id']}",json={"parent_id":second["id"]},headers=self.headers(self.MEMBER)))
        _,path=self.readable(node["id"],content)
        self.assertIn("资料二",path.parts)
        self.assertFalse(old_path.exists())
        old_path=path
        self.assert_ok(self.client.patch(f"/api/projects/{self.SPECIAL}",json={"name":"可读新项目"},headers=self.headers(self.DC_USER)))
        _,path=self.readable(node["id"],content)
        self.assertTrue(any("可读新项目" in part for part in path.parts))
        self.assertFalse(old_path.exists())

    def test_replace_keeps_same_readable_filename_and_downloads_updated_content(self):
        node=self.upload(self.SPECIAL,self.MEMBER,b"old contents",name="same-name.txt")
        _,path=self.readable(node["id"],b"old contents")
        self.assert_ok(self.client.post(f"/api/files/{node['id']}/replace",data={"file":(io.BytesIO(b"new contents"),"upload-name.txt")},headers=self.headers(self.MEMBER)))
        _,new_path=self.readable(node["id"],b"new contents","same-name.txt")
        self.assertEqual(path,new_path)
        self.assert_only_named_tree([new_path])
        response=self.client.get(f"/api/files/{node['id']}/download",headers=self.headers(self.MEMBER))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.data,b"new contents")
        response.close()

    def test_shared_aliases_materialize_separate_files_and_replace_independently(self):
        original=self.upload(self.SPECIAL,self.MEMBER,b"shared contents",name="shared.txt")
        alias=self.link(original["id"],self.SPECIAL,self.MEMBER)
        first,first_path=self.readable(original["id"],b"shared contents")
        second,second_path=self.readable(alias["id"],b"shared contents")
        self.assertNotEqual(first.id,second.id)
        self.assertNotEqual(first_path,second_path)
        self.assert_ok(self.client.post(f"/api/files/{alias['id']}/replace",data={"file":(io.BytesIO(b"alias update"),"ignored.txt")},headers=self.headers(self.MEMBER)))
        self.readable(alias["id"],b"alias update")
        self.assertEqual(first_path.read_bytes(),b"shared contents")
        self.assert_ok(self.client.delete(f"/api/files/{alias['id']}",headers=self.headers(self.MEMBER)))
        self.assertFalse(second_path.exists())
        self.assertEqual(first_path.read_bytes(),b"shared contents")

    def test_collision_suffix_and_long_name_preserve_every_file(self):
        first=self.upload(self.SPECIAL,self.MEMBER,b"first",name="a.txt")
        # Reserve a user's actual suffix-shaped filename before a duplicate.
        reserved=self.upload(self.SPECIAL,self.MEMBER,b"reserved",name=f"a [{first['id']+2}].txt")
        duplicate=self.upload(self.SPECIAL,self.MEMBER,b"duplicate",name="a.txt")
        for node,content in ((first,b"first"),(reserved,b"reserved"),(duplicate,b"duplicate")):
            self.readable(node["id"],content)
        names=[]
        for content in (b"long first",b"long second"):
            node=self.upload(self.SPECIAL,self.MEMBER,content,name="a"*216+".txt")
            _,path=self.readable(node["id"],content)
            names.append(path.name)
            self.assertLessEqual(len(path.name.encode("utf-8")),220)
        self.assertNotEqual(names[0],names[1])

    def test_folder_delete_recursively_removes_descendant_references_and_files(self):
        folder=self.folder("delete-tree")
        child=self.folder("nested",folder["id"])
        file=self.upload_in(child["id"],"child.txt",b"nested contents")
        _,path=self.readable(file["id"],b"nested contents")
        self.assert_ok(self.client.delete(f"/api/files/{folder['id']}",headers=self.headers(self.MEMBER)))
        db.session.expire_all()
        self.assertIsNotNone(db.session.get(FileNode,child["id"]).deleted_at)
        self.assertIsNotNone(db.session.get(FileNode,file["id"]).deleted_at)
        self.assertFalse(path.exists())
        self.assertEqual(self.client.get(f"/api/files/{file['id']}/download",headers=self.headers(self.MEMBER)).status_code,404)

    def test_empty_directory_rename_move_and_delete_leave_no_stale_directories(self):
        first=self.folder("empty-parent-a")
        second=self.folder("empty-parent-b")
        empty=self.folder("empty-original",first["id"])
        old=next(path for path in self.dc_root.rglob("empty-original") if path.is_dir())
        self.assert_ok(self.client.patch(f"/api/files/{empty['id']}",json={"name":"empty-renamed"},headers=self.headers(self.MEMBER)))
        self.assertFalse(old.exists())
        renamed=next(path for path in self.dc_root.rglob("empty-renamed") if path.is_dir())
        self.assert_ok(self.client.patch(f"/api/files/{empty['id']}",json={"parent_id":second["id"]},headers=self.headers(self.MEMBER)))
        self.assertFalse(renamed.exists())
        moved=next(path for path in self.dc_root.rglob("empty-renamed") if path.is_dir())
        self.assertEqual(moved.parent.name,"empty-parent-b")
        self.assert_ok(self.client.delete(f"/api/files/{empty['id']}",headers=self.headers(self.MEMBER)))
        self.assertFalse(moved.exists())

    def test_failed_commit_removes_new_empty_directory_and_keeps_existing_directory(self):
        self.folder("existing-directory")
        before={path for path in self.dc_root.rglob("*") if path.is_dir()}
        db.session.add(FileNode(type="folder",name="uncommitted-directory",parent_id=self.roots[self.SPECIAL],scope="project",project_id=self.SPECIAL,created_by=self.MEMBER))
        with patch.object(db.engine.dialect,"do_commit",side_effect=RuntimeError("simulated commit failure")):
            with self.assertRaises(RuntimeError):
                db.session.commit()
        db.session.remove()
        self.assertEqual({path for path in self.dc_root.rglob("*") if path.is_dir()},before)
        # Inspect durable state through an independent connection. The mocked
        # commit deliberately leaves SQLite's pooled driver transaction open.
        with contextlib.closing(sqlite3.connect(self.base/"test.sqlite")) as source:
            self.assertEqual(source.execute("SELECT COUNT(*) FROM file_nodes WHERE name='uncommitted-directory'").fetchone()[0],0)

    def test_ordinary_project_is_unchanged_after_readable_hooks_registered(self):
        node=self.upload(self.ORDINARY,self.DC_USER,b"legacy stays",name="normal.txt")
        stored=self.storage(node["id"])
        self.assertTrue(stored.storage_rel_path.startswith("objects/"))
        path=Path(resolve_object_path(stored.storage_rel_path))
        self.assertTrue(path.is_relative_to(self.legacy_root.resolve()))
        self.assertEqual(path.read_bytes(),b"legacy stays")
        self.assertFalse([path for path in self.dc_root.rglob("*") if path.is_file()])

    def test_zip_cache_is_outside_readable_root_and_archive_contents_are_correct(self):
        node=self.upload(self.SPECIAL,self.MEMBER,b"zip plain",name="zip.txt")
        with patch("app.api.threading.Thread",InlineThread):
            response=self.client.post(f"/api/files/{self.roots[self.SPECIAL]}/zip-tasks",headers=self.headers(self.MEMBER))
        task=self.assert_ok(response)["task"]
        self.assertEqual(task["status"],"done")
        response=self.client.get(f"/api/files/zip-tasks/{task['id']}/download",headers=self.headers(self.MEMBER))
        self.assertEqual(response.status_code,200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(archive.read(node["name"]),b"zip plain")
        response.close()
        self.assertFalse(list(self.dc_root.rglob("*.zip")))
        self.assertFalse((self.dc_root/"zip_tasks").exists())

    def test_failed_database_commit_and_session_close_restore_old_physical_content(self):
        node=self.upload(self.SPECIAL,self.MEMBER,b"AAA",name="rollback.txt")
        stored,target=self.readable(node["id"],b"AAA")
        original_rel=stored.storage_rel_path
        replacement_rel=f"_special_storage/projects/{self.SPECIAL}/objects/replacement-test"
        replacement=Path(resolve_object_path(replacement_rel))
        replacement.parent.mkdir(parents=True,exist_ok=True)
        replacement.write_bytes(b"BBB")
        stored.storage_rel_path=replacement_rel
        stored.sha256=None
        with patch.object(db.engine.dialect,"do_commit",side_effect=RuntimeError("simulated commit failure")):
            with self.assertRaises(RuntimeError):
                db.session.commit()
        db.session.remove()
        stored=self.storage(node["id"])
        self.assertEqual(stored.storage_rel_path,original_rel)
        self.assertEqual(target.read_bytes(),b"AAA")

    def test_history_cleanup_failure_does_not_report_a_failed_upload(self):
        with patch("app.readable_storage.shutil.move",side_effect=PermissionError("temporary history failure")):
            node=self.upload(self.SPECIAL,self.MEMBER,b"committed contents",name="cleanup.txt")
        self.readable(node["id"],b"committed contents","cleanup.txt")

    def sql_spy(self, statements):
        def capture(_connection, statement, _multiparams, _params, _options):
            statements.append(" ".join(str(statement.compile(dialect=mysql.dialect())).split()))
        engine=db.engine
        event.listen(engine,"before_execute",capture)
        self.addCleanup(lambda:event.remove(engine,"before_execute",capture))

    def test_project_lock_precedes_node_and_object_updates_and_current_tree_reads(self):
        node=self.upload(self.SPECIAL,self.MEMBER,b"serialized",name="before-lock.txt")
        statements=[]
        self.sql_spy(statements)
        db.session.get(FileNode,node["id"]).name="after-lock.txt"
        db.session.flush()
        locks=[index for index,sql in enumerate(statements) if sql.startswith("SELECT projects.id FROM projects") and sql.endswith("FOR UPDATE")]
        updates=[index for index,sql in enumerate(statements) if sql.startswith("UPDATE file_nodes")]
        self.assertTrue(locks and updates)
        self.assertLess(locks[0],updates[0])
        db.session.commit()
        self.assertTrue(any(sql.startswith("SELECT file_nodes.") and "FOR UPDATE" in sql for sql in statements))
        self.assertTrue(any(sql.startswith("SELECT projects.") and "FOR UPDATE" in sql for sql in statements))
        self.assertNotIn("readable_locked_projects",db.session.info)
        stored=self.storage(node["id"])
        replacement=f"_special_storage/projects/{self.SPECIAL}/objects/locking-replacement"
        raw=Path(resolve_object_path(replacement));raw.parent.mkdir(parents=True,exist_ok=True)
        raw.write_bytes(b"new payload")
        statements.clear()
        stored.storage_rel_path=replacement;stored.size_bytes=len(b"new payload");stored.sha256=None
        db.session.flush()
        lock=next(index for index,sql in enumerate(statements) if sql.startswith("SELECT projects.id FROM projects") and sql.endswith("FOR UPDATE"))
        change=next(index for index,sql in enumerate(statements) if sql.startswith("UPDATE storage_objects"))
        self.assertLess(lock,change)
        db.session.commit()
        self.readable(node["id"],b"new payload","after-lock.txt")

    def test_staged_retirement_and_removed_directories_restore_on_failed_commit(self):
        folder=self.folder("rollback-folder")
        node=self.upload_in(folder["id"],"rollback-retire.txt",b"original staged bytes")
        _,old_path=self.readable(node["id"],b"original staged bytes")
        old_directory=old_path.parent
        folder_object=db.session.get(FileNode,folder["id"])
        folder_object.name="new-folder"
        observed=[]
        def reject_commit(_connection):
            self.assertFalse(old_path.exists())
            self.assertFalse(old_directory.exists())
            self.assertTrue(db.session.info["readable_staged_retire"])
            self.assertIn(str(old_directory),db.session.info["readable_removed_dirs"])
            self.assertIn(self.SPECIAL,db.session.info["readable_locked_projects"])
            observed.extend(db.session.info["readable_staged_retire"])
            raise RuntimeError("fail after staging, before durable commit")
        with patch.object(db.engine.dialect,"do_commit",side_effect=reject_commit):
            with self.assertRaises(RuntimeError):
                db.session.commit()
        db.session.remove()
        self.assertTrue(old_directory.is_dir())
        self.assertEqual(old_path.read_bytes(),b"original staged bytes")
        self.assertFalse((old_directory.parent/"new-folder").exists())
        self.assertTrue(observed)
        self.assertFalse(any(Path(pending).exists() for pending,_ in observed))

    def test_after_commit_archiving_cannot_remove_a_reused_live_filename(self):
        node=self.upload(self.SPECIAL,self.MEMBER,b"transaction A",name="reused.txt")
        _,old_path=self.readable(node["id"],b"transaction A")
        import shutil
        original_move=shutil.move
        destinations=[]
        def concurrent_reuse(source,destination):
            self.assertTrue(Path(source).is_relative_to(self.base/"history"/".pending"))
            self.assertNotEqual(Path(source),old_path)
            if not destinations:
                self.assertFalse(old_path.exists())
                # Deterministically recreate the pathname after the database
                # commit releases its project lock but before A archives data.
                old_path.write_bytes(b"transaction B committed this pathname")
            destinations.append(Path(destination))
            return original_move(source,destination)
        with patch("app.readable_storage.shutil.move",side_effect=concurrent_reuse):
            self.assert_ok(self.client.patch(f"/api/files/{node['id']}",json={"name":"renamed.txt"},headers=self.headers(self.MEMBER)))
        self.assertTrue(destinations)
        self.assertEqual(old_path.read_bytes(),b"transaction B committed this pathname")
        self.readable(node["id"],b"transaction A","renamed.txt")
        self.assertTrue(any(path.read_bytes()==b"transaction A" for path in destinations))

    def test_standalone_migration_locks_before_updates_and_refreshes_cached_nodes(self):
        self.app.config["READABLE_STORAGE_ENABLED"]=False
        node=self.upload(self.SPECIAL,self.MEMBER,b"legacy fixture",name="cached-name.txt")
        cached=db.session.get(FileNode,node["id"])
        self.assertEqual(cached.name,"cached-name.txt")
        # A Core update deliberately leaves the ORM identity map stale.
        db.session.connection().execute(update(FileNode.__table__).where(FileNode.id==node["id"]).values(name="current-name.txt"))
        self.app.config["READABLE_STORAGE_ENABLED"]=True
        statements=[]
        self.sql_spy(statements)
        self.assertEqual(sync_project(self.SPECIAL),1)
        self.assertEqual(cached.name,"current-name.txt")
        lock=next(index for index,sql in enumerate(statements) if sql.startswith("SELECT projects.id FROM projects") and sql.endswith("FOR UPDATE"))
        change=next(index for index,sql in enumerate(statements) if sql.startswith("UPDATE storage_objects"))
        self.assertLess(lock,change)
        db.session.commit()
        self.readable(node["id"],b"legacy fixture","current-name.txt")

    def test_database_rollback_restores_files_before_releasing_project_lock(self):
        node=self.upload(self.SPECIAL,self.MEMBER,b"AAA",name="rollback-release.txt")
        stored,target=self.readable(node["id"],b"AAA")
        raw_rel=f"_special_storage/projects/{self.SPECIAL}/objects/rollback-release"
        raw=Path(resolve_object_path(raw_rel));raw.parent.mkdir(parents=True,exist_ok=True)
        raw.write_bytes(b"BBB")
        stored.storage_rel_path=raw_rel;stored.sha256=None
        original_rollback=db.engine.dialect.do_rollback
        released=[]
        def release_database_lock(connection):
            if not released:
                self.assertEqual(target.read_bytes(),b"AAA")
                self.assertFalse(db.session.info.get("readable_changes"))
                self.assertIn(self.SPECIAL,db.session.info["readable_locked_projects"])
                original_rollback(connection)
                # Represents the waiting writer proceeding after the DBAPI
                # rollback releases its lock but before Session rollback hooks.
                target.write_bytes(b"CCC committed by the next writer")
                released.append(True)
            else:
                original_rollback(connection)
        from app.readable_storage import _stage_retired_paths
        def reject_after_staging(session,relatives,directories):
            _stage_retired_paths(session,relatives,directories)
            self.assertEqual(target.read_bytes(),b"BBB")
            # A real SQL constraint error makes Session roll back its active
            # transaction; a mocked do_commit error deactivates SQLAlchemy's
            # transaction without invoking the driver's rollback in SQLite.
            session.add(StorageObject(storage_rel_path=stored.storage_rel_path,size_bytes=3,created_by=self.MEMBER))
            session.flush()
        with patch.object(db.engine.dialect,"do_rollback",side_effect=release_database_lock):
            with patch("app.readable_storage._stage_retired_paths",side_effect=reject_after_staging):
                with self.assertRaises(IntegrityError):
                    db.session.commit()
            db.session.remove()
        self.assertEqual(released,[True])
        self.assertEqual(target.read_bytes(),b"CCC committed by the next writer")
        self.assertNotIn("readable_connection_info",db.session.info)


if __name__=="__main__":
    unittest.main()
