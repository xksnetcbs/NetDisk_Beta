"""Storage-policy regressions using only temporary files and a temporary SQLite DB.

No application configuration is loaded, so this suite cannot connect to the
configured database or write to either real storage directory.
"""

import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from flask import Flask
from flask_jwt_extended import create_access_token
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles

from app.api import ZIP_TASKS, api_bp
from app.extensions import db, jwt
from app.models import FileNode, Project, ProjectMember, StorageObject, User
from app.services import create_file_node, create_folder
from app.storage import (
    dc_storage_root,
    is_dc_project,
    migrate_dc_project,
    new_object_path,
    resolve_object_path,
)


@compiles(BigInteger, "sqlite")
def sqlite_big_integer(_type, _compiler, **_kwargs):
    """SQLite generates primary keys only when the declared type is INTEGER."""
    return "INTEGER"


class InlineThread:
    """Run the ZIP worker deterministically while retaining its real code path."""

    def __init__(self, target, args=(), **_kwargs):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


class ProjectStorageTests(unittest.TestCase):
    DC_USER = 1
    MEMBER = 2
    OTHER_ADMIN = 3
    OWNER = 4
    SPECIAL = 101
    ORDINARY = 102
    OWNED_SPECIAL = 103
    OTHER_ADMIN_PROJECT = 104

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="netdisk-storage-test-")
        self.base = Path(self.temporary.name)
        self.legacy_root = self.base / "legacy"
        self.dc_root = self.base / "Net_Disk"
        self.legacy_root.mkdir()
        self.dc_root.mkdir()
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///" + str(self.base / "test.sqlite"),
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            SECRET_KEY="temporary-storage-test-secret-key",
            JWT_SECRET_KEY="temporary-storage-test-jwt-secret-key",
            STORAGE_ROOT=str(self.legacy_root),
            SPECIAL_STORAGE_ROOT=str(self.dc_root),
            MAX_UPLOAD_MB=2,
        )
        db.init_app(self.app)
        jwt.init_app(self.app)
        self.app.register_blueprint(api_bp, url_prefix="/api")
        self.context = self.app.app_context()
        self.context.push()
        # Match MySQL's monotonic IDs: deleted FileNodes retain historical
        # object IDs, so SQLite's default row-ID reuse would invent aliases.
        for table in db.metadata.tables.values():
            table.dialect_options["sqlite"]["autoincrement"] = True
        db.create_all()
        for user_id, username, role in (
            (self.DC_USER, "storage_admin", "super_admin"),
            (self.MEMBER, "ordinary_member", "user"),
            (self.OTHER_ADMIN, "another_admin", "super_admin"),
            (self.OWNER, "ordinary_owner", "user"),
        ):
            db.session.add(User(
                id=user_id, username=username, display_name=username,
                password_hash="unused-test-password-hash", role_system=role,
                status="active", is_activated=True,
            ))
        for project_id, creator in (
            (self.SPECIAL, self.DC_USER),
            (self.ORDINARY, self.OWNER),
            (self.OWNED_SPECIAL, self.OWNER),
            (self.OTHER_ADMIN_PROJECT, self.OTHER_ADMIN),
        ):
            db.session.add(Project(
                id=project_id, name=f"Project {project_id}",
                key=f"TEST_{project_id}", creator_id=creator,
            ))
            db.session.add(ProjectMember(
                project_id=project_id, user_id=self.MEMBER, role_project="user",
            ))
        db.session.add(ProjectMember(
            project_id=self.OWNED_SPECIAL, user_id=self.DC_USER,
            role_project="creator",
        ))
        # Administrative visibility/membership alone is not project ownership.
        db.session.add(ProjectMember(
            project_id=self.ORDINARY, user_id=self.DC_USER, role_project="admin",
        ))
        db.session.flush()
        self.roots = {}
        for project_id in (self.SPECIAL, self.ORDINARY, self.OWNED_SPECIAL, self.OTHER_ADMIN_PROJECT):
            self.roots[project_id] = int(create_folder(
                "root", None, "project", None, project_id, self.OWNER,
            ).id)
        self.personal_root = int(create_folder(
            "root", None, "personal", self.DC_USER, None, self.DC_USER,
        ).id)
        db.session.commit()
        self.tokens = {
            user_id: create_access_token(identity=str(user_id))
            for user_id in (self.DC_USER, self.MEMBER, self.OTHER_ADMIN, self.OWNER)
        }
        self.client = self.app.test_client()
        ZIP_TASKS.clear()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        ZIP_TASKS.clear()
        self.temporary.cleanup()

    def headers(self, user_id):
        return {"Authorization": "Bearer " + self.tokens[user_id]}

    def test_configured_storage_owner_controls_created_and_owned_projects(self):
        self.app.config["SPECIAL_STORAGE_USERNAME"] = "configured_storage_owner"
        self.assertFalse(is_dc_project(self.SPECIAL))
        owner = db.session.get(User, self.DC_USER)
        owner.username = "configured_storage_owner"
        db.session.commit()
        self.assertTrue(is_dc_project(self.SPECIAL))
        self.assertTrue(is_dc_project(self.OWNED_SPECIAL))
        self.assertFalse(is_dc_project(self.ORDINARY))
        self.assertFalse(is_dc_project(self.OTHER_ADMIN_PROJECT))

    def assert_ok(self, response):
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        body = response.get_json()
        self.assertTrue(body["ok"], body)
        return body["data"]

    def upload(self, project_id, user_id=MEMBER, content=b"original contents", name="readme.txt"):
        scope = "project" if project_id is not None else "personal"
        data = {
            "scope": scope,
            "parent_id": str(self.roots[project_id] if project_id is not None else self.personal_root),
            "file": (io.BytesIO(content), name, "text/plain"),
        }
        if project_id is not None:
            data["project_id"] = str(project_id)
        response = self.client.post("/api/files/upload", data=data, headers=self.headers(user_id))
        return self.assert_ok(response)["file"]

    def storage(self, file_id):
        db.session.expire_all()
        node = db.session.get(FileNode, int(file_id))
        return db.session.get(StorageObject, int(node.storage_object_id))

    def assert_storage(self, file_id, project_id, content):
        stored = self.storage(file_id)
        path = Path(resolve_object_path(stored.storage_rel_path))
        if project_id in (self.SPECIAL, self.OWNED_SPECIAL):
            self.assertTrue(stored.storage_rel_path.startswith(f"_special_storage/projects/{project_id}/"))
            self.assertTrue(path.is_relative_to(self.dc_root.resolve()))
        else:
            self.assertTrue(stored.storage_rel_path.startswith("objects/"))
            self.assertTrue(path.is_relative_to(self.legacy_root.resolve()))
        self.assertEqual(path.read_bytes(), content)
        self.assertEqual(stored.size_bytes, len(content))
        return stored, path

    def link(self, source_file_id, target_project, user_id=DC_USER):
        data = {
            "source_file_id": source_file_id,
            "target_scope": "project" if target_project is not None else "personal",
            "target_parent_id": self.roots[target_project] if target_project is not None else self.personal_root,
        }
        if target_project is not None:
            data["target_project_id"] = target_project
        else:
            data["target_owner_user_id"] = self.DC_USER
        response = self.client.post("/api/files/link", json=data, headers=self.headers(user_id))
        return self.assert_ok(response)["file"]

    def seed_legacy_shared_object(self, projects, content=b"shared legacy data"):
        path = self.legacy_root / "objects" / "legacy" / "shared.bin"
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
        stored = StorageObject(
            mime_type="application/octet-stream", size_bytes=len(content),
            storage_rel_path="objects/legacy/shared.bin", created_by=self.MEMBER,
        )
        db.session.add(stored)
        db.session.flush()
        nodes = [
            create_file_node(
                "shared.bin", self.roots[project_id], "project", None,
                project_id, int(stored.id), self.MEMBER,
            )
            for project_id in projects
        ]
        db.session.commit()
        return int(stored.id), [int(node.id) for node in nodes], path

    def test_project_ownership_policy_is_independent_of_uploader_permissions(self):
        self.assertTrue(is_dc_project(self.SPECIAL))
        self.assertTrue(is_dc_project(self.OWNED_SPECIAL))
        self.assertFalse(is_dc_project(self.ORDINARY))
        self.assertFalse(is_dc_project(self.OTHER_ADMIN_PROJECT))
        self.assertFalse(is_dc_project(999999))
        self.assertFalse(is_dc_project(None))
        for project_id, uploader in (
            (self.SPECIAL, self.MEMBER),
            (self.OWNED_SPECIAL, self.MEMBER),
            (self.ORDINARY, self.DC_USER),
            (self.OTHER_ADMIN_PROJECT, self.OTHER_ADMIN),
            (None, self.DC_USER),
        ):
            with self.subTest(project=project_id, uploader=uploader):
                content = f"project {project_id} uploaded by {uploader}".encode()
                node = self.upload(project_id, uploader, content)
                self.assert_storage(node["id"], project_id, content)

    def test_named_account_must_also_be_super_admin(self):
        owner = db.session.get(User, self.DC_USER)
        owner.role_system = "user"
        db.session.commit()
        self.assertFalse(is_dc_project(self.SPECIAL))
        self.assertFalse(is_dc_project(self.OWNED_SPECIAL))
        self.assertFalse(new_object_path(self.SPECIAL).startswith("_special_storage/"))

    def test_default_special_root_is_home_net_disk(self):
        del self.app.config["SPECIAL_STORAGE_ROOT"]
        self.assertEqual(dc_storage_root(), os.path.abspath(os.path.expanduser("~/Net_Disk")))

    def test_resumable_upload_routes_to_target_project_and_removes_session(self):
        content = b"0123456789abcdef"
        for project_id, uploader in ((self.SPECIAL, self.MEMBER), (self.ORDINARY, self.DC_USER)):
            with self.subTest(project=project_id):
                response = self.client.post("/api/files/upload-sessions", json={
                    "filename": "chunks.txt", "size": len(content), "chunk_size": 5,
                    "scope": "project", "project_id": project_id,
                    "parent_id": self.roots[project_id], "mime_type": "text/plain",
                }, headers=self.headers(uploader))
                session_id = self.assert_ok(response)["session"]["upload_id"]
                for index, offset in enumerate(range(0, len(content), 5)):
                    self.assert_ok(self.client.put(
                        f"/api/files/upload-sessions/{session_id}/chunks/{index}",
                        data=content[offset:offset + 5], headers=self.headers(uploader),
                        content_type="application/octet-stream",
                    ))
                response = self.client.post(
                    f"/api/files/upload-sessions/{session_id}/complete", headers=self.headers(uploader),
                )
                node = self.assert_ok(response)["file"]
                self.assert_storage(node["id"], project_id, content)
                self.assertFalse((self.legacy_root / "uploads" / session_id).exists())
                self.assertFalse((self.dc_root / "uploads" / session_id).exists())

    def test_incomplete_resumable_upload_creates_no_object(self):
        response = self.client.post("/api/files/upload-sessions", json={
            "filename": "incomplete.txt", "size": 10, "chunk_size": 5,
            "scope": "project", "project_id": self.SPECIAL,
            "parent_id": self.roots[self.SPECIAL],
        }, headers=self.headers(self.MEMBER))
        session_id = self.assert_ok(response)["session"]["upload_id"]
        response = self.client.post(
            f"/api/files/upload-sessions/{session_id}/complete", headers=self.headers(self.MEMBER),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "UPLOAD_INCOMPLETE")
        self.assertEqual(StorageObject.query.count(), 0)
        self.assertFalse(list(self.dc_root.rglob("*.tmp")))

    def test_download_preview_zip_replace_and_delete_use_correct_root(self):
        for project_id, uploader in ((self.SPECIAL, self.MEMBER), (self.ORDINARY, self.DC_USER), (None, self.DC_USER)):
            with self.subTest(project=project_id):
                content = f"contents for {project_id}".encode()
                node = self.upload(project_id, uploader, content, name=f"sample-{project_id}.txt")
                stored, old_path = self.assert_storage(node["id"], project_id, content)
                stored_id = int(stored.id)
                response = self.client.get(f"/api/files/{node['id']}/download", headers=self.headers(uploader))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, content)
                response.close()
                response = self.client.get(
                    f"/api/files/{node['id']}/preview", query_string={"token": self.tokens[uploader]},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, content)
                response.close()
                folder_id = self.roots[project_id] if project_id is not None else self.personal_root
                with patch("app.api.threading.Thread", InlineThread):
                    response = self.client.post(
                        f"/api/files/{folder_id}/zip-tasks", headers=self.headers(uploader),
                    )
                task = self.assert_ok(response)["task"]
                self.assertEqual(task["status"], "done", task)
                response = self.client.get(
                    f"/api/files/zip-tasks/{task['id']}/download", headers=self.headers(uploader),
                )
                self.assertEqual(response.status_code, 200)
                with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                    self.assertEqual(archive.read(node["name"]), content)
                response.close()
                updated = b"updated contents"
                self.assert_ok(self.client.post(
                    f"/api/files/{node['id']}/replace",
                    data={"file": (io.BytesIO(updated), "updated.txt", "text/plain")},
                    headers=self.headers(uploader),
                ))
                _, new_path = self.assert_storage(node["id"], project_id, updated)
                self.assertNotEqual(old_path, new_path)
                self.assertFalse(old_path.exists())
                self.assert_ok(self.client.delete(f"/api/files/{node['id']}", headers=self.headers(uploader)))
                self.assertFalse(new_path.exists())
                db.session.expire_all()
                self.assertIsNone(db.session.get(StorageObject, stored_id))
                response = self.client.get(f"/api/files/{node['id']}/download", headers=self.headers(uploader))
                self.assertEqual(response.status_code, 404)

    def test_cross_root_links_copy_contents_without_relocating_source(self):
        for source_project, target_project in ((self.ORDINARY, self.SPECIAL), (self.SPECIAL, self.ORDINARY), (self.SPECIAL, None), (self.SPECIAL, self.OWNED_SPECIAL)):
            with self.subTest(source=source_project, target=target_project):
                content = f"copy from {source_project} to {target_project}".encode()
                source = self.upload(source_project, self.DC_USER, content)
                source_stored, source_path = self.assert_storage(source["id"], source_project, content)
                original_id = int(source_stored.id)
                original_rel = source_stored.storage_rel_path
                linked = self.link(source["id"], target_project)
                copied, _ = self.assert_storage(linked["id"], target_project, content)
                self.assertNotEqual(int(copied.id), original_id)
                self.assertEqual(self.storage(source["id"]).storage_rel_path, original_rel)
                self.assertEqual(source_path.read_bytes(), content)
                self.assert_ok(self.client.delete(f"/api/files/{linked['id']}", headers=self.headers(self.DC_USER)))
                self.assertEqual(source_path.read_bytes(), content)

    def test_same_project_links_keep_shared_content_until_last_reference_deleted(self):
        content = b"same-project shared contents"
        source = self.upload(self.SPECIAL, self.MEMBER, content)
        linked = self.link(source["id"], self.SPECIAL, self.MEMBER)
        self.assertEqual(source["storage_object_id"], linked["storage_object_id"])
        _, path = self.assert_storage(source["id"], self.SPECIAL, content)
        self.assert_ok(self.client.delete(f"/api/files/{source['id']}", headers=self.headers(self.MEMBER)))
        self.assertEqual(path.read_bytes(), content)
        self.assert_ok(self.client.delete(f"/api/files/{linked['id']}", headers=self.headers(self.MEMBER)))
        self.assertFalse(path.exists())

    def test_replacing_unmigrated_special_alias_does_not_change_ordinary_storage(self):
        original = b"shared before migration"
        original_id, node_ids, old_path = self.seed_legacy_shared_object([self.SPECIAL, self.ORDINARY], original)
        updated = b"special project updated contents"
        self.assert_ok(self.client.post(
            f"/api/files/{node_ids[0]}/replace",
            data={"file": (io.BytesIO(updated), "updated.bin", "application/octet-stream")},
            headers=self.headers(self.MEMBER),
        ))
        self.assert_storage(node_ids[0], self.SPECIAL, updated)
        ordinary = self.storage(node_ids[1])
        self.assertEqual(ordinary.id, original_id)
        self.assertEqual(ordinary.storage_rel_path, "objects/legacy/shared.bin")
        self.assertEqual(old_path.read_bytes(), original)

    def test_shared_legacy_migration_splits_each_special_project_and_preserves_ordinary(self):
        content = b"original legacy shared contents"
        original_id, node_ids, old_path = self.seed_legacy_shared_object(
            [self.SPECIAL, self.SPECIAL, self.OWNED_SPECIAL, self.ORDINARY], content,
        )
        first = migrate_dc_project(self.SPECIAL)
        self.assertEqual((first["copied"], first["nodes"]), (1, 2))
        self.assertEqual(first["missing"], [])
        self.assertEqual(first["errors"], [])
        special_objects = [self.storage(node_id).id for node_id in node_ids[:2]]
        self.assertEqual(special_objects[0], special_objects[1])
        self.assertNotEqual(special_objects[0], original_id)
        self.assertEqual(self.storage(node_ids[2]).id, original_id)
        self.assertEqual(self.storage(node_ids[3]).id, original_id)
        second = migrate_dc_project(self.OWNED_SPECIAL)
        self.assertEqual((second["copied"], second["nodes"]), (1, 1))
        self.assert_storage(node_ids[0], self.SPECIAL, content)
        self.assert_storage(node_ids[2], self.OWNED_SPECIAL, content)
        ordinary = self.storage(node_ids[3])
        self.assertEqual(ordinary.id, original_id)
        self.assertEqual(ordinary.storage_rel_path, "objects/legacy/shared.bin")
        self.assertEqual(old_path.read_bytes(), content)
        self.assertEqual(migrate_dc_project(self.SPECIAL)["copied"], 0)
        self.assertEqual(migrate_dc_project(self.ORDINARY)["copied"], 0)

    def test_migration_dry_run_leaves_database_and_files_unchanged(self):
        original_id, node_ids, old_path = self.seed_legacy_shared_object([self.SPECIAL, self.ORDINARY])
        before_files = sorted(str(path.relative_to(self.base)) for path in self.base.rglob("*") if path.is_file())
        result = migrate_dc_project(self.SPECIAL, dry_run=True)
        self.assertEqual((result["copied"], result["nodes"]), (1, 1))
        self.assertEqual(StorageObject.query.count(), 1)
        self.assertEqual([self.storage(node_id).id for node_id in node_ids], [original_id, original_id])
        after_files = sorted(str(path.relative_to(self.base)) for path in self.base.rglob("*") if path.is_file())
        self.assertEqual(before_files, after_files)
        self.assertTrue(old_path.exists())

    def test_missing_migration_source_retains_existing_reference(self):
        original_id, node_ids, old_path = self.seed_legacy_shared_object([self.SPECIAL])
        old_path.unlink()
        result = migrate_dc_project(self.SPECIAL)
        self.assertEqual(result["missing"], [original_id])
        self.assertEqual(result["copied"], 0)
        self.assertEqual(self.storage(node_ids[0]).id, original_id)
        self.assertEqual(StorageObject.query.count(), 1)

    def test_failed_copy_verification_preserves_source_and_reference(self):
        original_id, node_ids, old_path = self.seed_legacy_shared_object([self.SPECIAL])
        original = old_path.read_bytes()

        def write_incomplete_copy(_source, target):
            Path(target).write_bytes(b"incomplete")

        with patch("app.storage.shutil.copyfile", write_incomplete_copy):
            result = migrate_dc_project(self.SPECIAL)
        self.assertEqual(result["copied"], 0)
        self.assertEqual(result["errors"], [{"object_id": original_id, "type": "OSError"}])
        self.assertEqual(self.storage(node_ids[0]).id, original_id)
        self.assertEqual(old_path.read_bytes(), original)
        self.assertEqual(StorageObject.query.count(), 1)
        self.assertFalse([path for path in self.dc_root.rglob("*") if path.is_file()])

    def test_explicit_source_root_allows_migration_from_original_legacy_directory(self):
        _, node_ids, old_path = self.seed_legacy_shared_object([self.SPECIAL])
        self.app.config["STORAGE_ROOT"] = str(self.base / "other-legacy-root")
        result = migrate_dc_project(self.SPECIAL, source_root=str(self.legacy_root))
        self.assertEqual(result["copied"], 1)
        self.assertEqual(result["errors"], [])
        self.assertEqual(Path(resolve_object_path(self.storage(node_ids[0]).storage_rel_path)).read_bytes(), old_path.read_bytes())
        self.assertTrue(old_path.exists())

    def test_readable_incoming_namespace_requires_both_configuration_and_extension(self):
        self.app.config["READABLE_STORAGE_ENABLED"] = True
        self.assertTrue(new_object_path(self.SPECIAL).startswith(f"_special_storage/projects/{self.SPECIAL}/objects/"))
        self.app.extensions["readable_storage"] = True
        incoming = new_object_path(self.SPECIAL)
        self.assertTrue(incoming.startswith(f"_special_storage/projects/{self.SPECIAL}/incoming/objects/"))
        self.assertTrue(new_object_path(self.ORDINARY).startswith("objects/"))
        self.assertTrue(new_object_path().startswith("objects/"))
        self.app.config["READABLE_STORAGE_ENABLED"] = False
        self.assertTrue(new_object_path(self.SPECIAL).startswith(f"_special_storage/projects/{self.SPECIAL}/objects/"))

    def test_incoming_resolves_explicit_history_address_without_changing_old_addresses(self):
        incoming = f"_special_storage/projects/{self.SPECIAL}/incoming/objects/2026/10/staged"
        suffix = Path("projects") / str(self.SPECIAL) / "objects" / "2026" / "10" / "staged"
        self.assertEqual(Path(resolve_object_path(incoming)), self.base / ".netdisk-storage-history" / ".incoming" / suffix)
        self.app.config.update(READABLE_HISTORY_ROOT=str(self.base / "history"), READABLE_STORAGE_ENABLED=False)
        self.assertEqual(Path(resolve_object_path(incoming)), self.base / "history" / ".incoming" / suffix)
        old = f"_special_storage/projects/{self.SPECIAL}/objects/2026/10/staged"
        self.assertEqual(Path(resolve_object_path(old)), self.dc_root / suffix)
        tree = f"_special_storage/projects/{self.SPECIAL}/tree/Named project/report.txt"
        self.assertEqual(Path(resolve_object_path(tree)), self.dc_root / "Named project" / "report.txt")

    def test_object_path_rejects_traversal_absolute_and_drive_paths(self):
        for invalid in (
            "", "../escape.bin", "objects/../../escape.bin", "objects/./file.bin",
            "objects//file.bin", "/absolute.bin", "C:/escape.bin", "C:escape.bin",
            "\\\\server\\share\\escape.bin", "_special_storage/../escape.bin",
            "_special_storage/projects/101/../../../../escape.bin",
            "_special_storage/projects/101/incoming/objects/../../../../escape.bin",
            "_special_storage/projects/101/incoming/objects//file.bin",
            "_special_storage/C:/escape.bin", "_special_storage/\\absolute.bin",
        ):
            with self.subTest(path=invalid):
                with self.assertRaises(ValueError):
                    resolve_object_path(invalid)
        self.assertEqual(resolve_object_path("objects/legacy/file.bin"), str(self.legacy_root / "objects" / "legacy" / "file.bin"))
        self.assertEqual(resolve_object_path("_special_storage/projects/101/objects/file.bin"), str(self.dc_root / "projects" / "101" / "objects" / "file.bin"))

    def test_download_rejects_corrupt_path_instead_of_reading_outside_root(self):
        _, node_ids, _ = self.seed_legacy_shared_object([self.ORDINARY])
        outside = self.base / "outside.txt"
        outside.write_bytes(b"must never be downloaded")
        stored = self.storage(node_ids[0])
        stored.storage_rel_path = "../outside.txt"
        db.session.commit()
        response = self.client.get(f"/api/files/{node_ids[0]}/download", headers=self.headers(self.MEMBER))
        self.assertEqual(response.status_code, 403)
        self.assertNotEqual(response.data, outside.read_bytes())


if __name__ == "__main__":
    unittest.main()
