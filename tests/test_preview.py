"""Authenticated previews and range requests against temporary project storage."""
import unittest
from unittest.mock import patch
from pathlib import Path
from app.extensions import db
from app.models import ProjectMember
import shutil
from types import SimpleNamespace
import test_project_storage as fixtures


class PreviewTests(unittest.TestCase):
    setUp = fixtures.ProjectStorageTests.setUp
    tearDown = fixtures.ProjectStorageTests.tearDown
    headers = fixtures.ProjectStorageTests.headers
    assert_ok = fixtures.ProjectStorageTests.assert_ok
    upload = fixtures.ProjectStorageTests.upload
    DC_USER = fixtures.ProjectStorageTests.DC_USER
    MEMBER = fixtures.ProjectStorageTests.MEMBER
    OTHER_ADMIN = fixtures.ProjectStorageTests.OTHER_ADMIN
    OWNER = fixtures.ProjectStorageTests.OWNER
    SPECIAL = fixtures.ProjectStorageTests.SPECIAL
    ORDINARY = fixtures.ProjectStorageTests.ORDINARY
    OWNED_SPECIAL = fixtures.ProjectStorageTests.OWNED_SPECIAL
    OTHER_ADMIN_PROJECT = fixtures.ProjectStorageTests.OTHER_ADMIN_PROJECT

    def test_bearer_preview_preserves_bytes_and_supports_media_range(self):
        data = b"native authenticated preview bytes"
        node = self.upload(self.SPECIAL, self.DC_USER, data, "clip.mp4")
        route = f"/api/files/{node['id']}/preview"
        response = self.client.get(route, headers=self.headers(self.MEMBER))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, data)
        response.close()
        response = self.client.get(route, headers={**self.headers(self.MEMBER), "Range": "bytes=2-6"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.data, data[2:7])
        self.assertEqual(response.headers["Content-Range"], f"bytes 2-6/{len(data)}")
        response.close()

    def test_current_project_membership_gates_preview_and_legacy_url_still_works(self):
        node = self.upload(self.SPECIAL, self.DC_USER, b"# Native notes\n", "notes.md")
        route = f"/api/files/{node['id']}/preview"
        response = self.client.get(route, query_string={"token": self.tokens[self.MEMBER]})
        self.assertEqual(response.status_code, 200)
        response.close()
        ProjectMember.query.filter_by(project_id=self.SPECIAL, user_id=self.MEMBER).delete()
        db.session.commit()
        self.assertEqual(self.client.get(route, headers=self.headers(self.MEMBER)).status_code, 403)

    def test_invalid_authorization_never_falls_back_to_url_token(self):
        node = self.upload(self.SPECIAL, self.DC_USER, b"preview", "notes.txt")
        route = f"/api/files/{node['id']}/preview"
        self.assertEqual(self.client.get(route).status_code, 401)
        response = self.client.get(route, headers={"Authorization": "Bearer invalid"}, query_string={"token": self.tokens[self.DC_USER]})
        self.assertEqual(response.status_code, 401)

    def test_office_conversion_rechecks_membership_before_releasing_pdf(self):
        node = self.upload(self.SPECIAL, self.DC_USER, b"temporary office source", "notes.docx")
        def convert_then_remove(_source, _name, target):
            Path(target).write_bytes(b"%PDF-temporary-test-result")
            ProjectMember.query.filter_by(project_id=self.SPECIAL, user_id=self.MEMBER).delete()
            db.session.commit()
        with patch("app.api.convert_office_to_pdf", side_effect=convert_then_remove):
            response = self.client.get(f"/api/files/{node['id']}/preview", headers=self.headers(self.MEMBER))
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"%PDF", response.data)

    def test_office_cache_is_published_only_after_complete_copy(self):
        from app.api import convert_office_to_pdf
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "word.docx"
            source.write_bytes(b"temporary office source")
            cache = Path(directory) / "cache"
            cache.mkdir()
            target = cache / "ready.pdf"
            target.write_bytes(b"%PDF-old-complete")
            original_copy = shutil.copyfile
            seen = []
            def convert(command, **_kwargs):
                output = Path(command[command.index("--outdir") + 1]) / "word.pdf"
                output.write_bytes(b"%PDF-new-complete")
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            def copy(source_path, destination, *args, **kwargs):
                destination = Path(destination)
                if destination.parent == cache:
                    self.assertNotEqual(destination, target)
                    self.assertEqual(target.read_bytes(), b"%PDF-old-complete")
                    seen.append(destination)
                return original_copy(source_path, destination, *args, **kwargs)
            with patch("app.api.find_soffice_bin", return_value="synthetic-soffice"), patch("app.api.subprocess.run", side_effect=convert), patch("app.api.shutil.copyfile", side_effect=copy):
                self.assertIsNone(convert_office_to_pdf(str(source), source.name, str(target)))
            self.assertEqual(target.read_bytes(), b"%PDF-new-complete")
            self.assertEqual(len(seen), 1)
            self.assertFalse(seen[0].exists())

    def test_failed_office_cache_publication_retains_complete_previous_pdf(self):
        from app.api import convert_office_to_pdf
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "word.docx"
            source.write_bytes(b"temporary office source")
            cache = Path(directory) / "cache"
            cache.mkdir()
            target = cache / "ready.pdf"
            target.write_bytes(b"%PDF-old-complete")
            original_copy = shutil.copyfile
            def convert(command, **_kwargs):
                (Path(command[command.index("--outdir") + 1]) / "word.pdf").write_bytes(b"%PDF-new-complete")
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            def copy(source_path, destination, *args, **kwargs):
                if Path(destination).parent == cache:
                    Path(destination).write_bytes(b"partial")
                    raise OSError("synthetic incomplete copy")
                return original_copy(source_path, destination, *args, **kwargs)
            with patch("app.api.find_soffice_bin", return_value="synthetic-soffice"), patch("app.api.subprocess.run", side_effect=convert), patch("app.api.shutil.copyfile", side_effect=copy):
                with self.assertRaises(OSError):
                    convert_office_to_pdf(str(source), source.name, str(target))
            self.assertEqual(target.read_bytes(), b"%PDF-old-complete")
            self.assertEqual(list(cache.iterdir()), [target])


if __name__ == "__main__":
    unittest.main()
