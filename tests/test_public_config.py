"""Portable publication configuration never falls back to shipped credentials."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.config import Config, load_config


class PublicConfigTests(unittest.TestCase):
    def load(self, values):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps(values), encoding="utf-8")
            with patch.dict(os.environ, {"NETDISK_CONFIG": str(path)}), patch.multiple(
                Config, SECRET_KEY="", JWT_SECRET_KEY="", SQLALCHEMY_DATABASE_URI=None,
                SPECIAL_STORAGE_USERNAME="storage_admin",
            ):
                config = load_config()
                return config.SPECIAL_STORAGE_USERNAME

    def test_external_configuration_accepts_private_keys_and_custom_owner(self):
        self.assertEqual(self.load({
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SECRET_KEY": "isolated-test-key-" * 4,
            "JWT_SECRET_KEY": "isolated-test-jwt-key-" * 4,
            "SPECIAL_STORAGE_USERNAME": "configured_storage_owner",
        }), "configured_storage_owner")

    def test_example_configuration_cannot_be_used_with_placeholder_keys(self):
        with self.assertRaisesRegex(RuntimeError, "SECRET_KEY"):
            self.load({
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "SECRET_KEY": "REPLACE_WITH_PRIVATE_RANDOM_SECRET_KEY",
                "JWT_SECRET_KEY": "REPLACE_WITH_PRIVATE_RANDOM_JWT_SECRET_KEY",
            })

    def test_missing_database_is_rejected_before_connecting(self):
        with self.assertRaisesRegex(RuntimeError, "SQLALCHEMY_DATABASE_URI"):
            self.load({})
