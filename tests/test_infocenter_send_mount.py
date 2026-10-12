"""Check fork send routes without launching the actual WeChat controller."""

import importlib.util
import base64
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from flask import Flask


class InfoCenterSendMountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        home = Path(self.temp.name)
        (home / "config.json").write_text(json.dumps({"token": "mock-terminal-token"}), encoding="utf-8")
        server = Path(__file__).resolve().parents[1] / "integrations/DCP_InfoCenter/server"
        path_patch = patch.object(sys, "path", [str(server)] + sys.path)
        path_patch.start()
        self.addCleanup(path_patch.stop)
        spec = importlib.util.spec_from_file_location("infocenter_desktop_send_fixture", server / "desktop_api.py")
        desktop = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(desktop)
        self.store = types.SimpleNamespace(home=home, directory={"mock-contact": {"name": "唯一测试联系人"}}, refresh=lambda: None)
        self.app = Flask("infocenter-send-fixture")
        desktop.mount(self.app, store=self.store)
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer mock-terminal-token"}
        self.sender = patch("send_api.subprocess.run")
        self.run = self.sender.start()
        self.addCleanup(self.sender.stop)
        self.run.return_value = types.SimpleNamespace(returncode=0, stdout='{"status":"mocked"}')

    def test_all_send_routes_are_mounted_and_authentication_precedes_controller(self):
        paths = {str(rule) for rule in self.app.url_map.iter_rules()}
        self.assertIn("/api/terminal/desktop/send/prepare", paths)
        self.assertIn("/api/terminal/desktop/send/<action>", paths)
        result = self.client.post("/api/terminal/desktop/send/prepare", json={"chat": "mock-contact"})
        self.assertEqual(result.status_code, 401)
        self.run.assert_not_called()

    def test_legacy_prepare_calls_send_and_cancel_is_forwarded_with_mock_only(self):
        prepared = self.client.post("/api/terminal/desktop/send/prepare", headers=self.headers,
                                    json={"id": "mock-request-id-123456", "chat": "mock-contact", "text": "mock-only"})
        self.assertEqual(prepared.status_code, 200)
        self.assertEqual(json.loads(self.run.call_args.kwargs["input"])["action"], "send")
        # The original prepare endpoint performs a direct send. Keep this regression
        # check mocked; never use it as a supposedly harmless live prepare probe.
        cancelled = self.client.post("/api/terminal/desktop/send/cancel", headers=self.headers,
                                     json={"id": "mock-request-id-123456"})
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(json.loads(self.run.call_args.kwargs["input"])["action"], "cancel")

    def test_unknown_recipient_never_launches_controller(self):
        result = self.client.post("/api/terminal/desktop/send/prepare", headers=self.headers,
                                 json={"chat": "unknown-wechat-contact", "text": "not-a-wechat-recipient"})
        self.assertEqual(result.status_code, 400)
        self.run.assert_not_called()

    def test_virtual_recipient_is_rejected_even_if_directory_has_a_matching_name(self):
        self.store.directory["netdisk:mock:thread:1"] = {"name": "唯一测试联系人"}
        result = self.client.post("/api/terminal/desktop/send/prepare", headers=self.headers,
                                 json={"chat": "netdisk:mock:thread:1", "text": "must-stay-in-netdisk"})
        self.assertEqual(result.status_code, 400)
        self.assertIn("NetDisk", result.json["error"])
        self.run.assert_not_called()

    def test_sidecar_allows_original_large_attachment_only_on_send_routes(self):
        server = Path(__file__).resolve().parents[1] / "integrations/DCP_InfoCenter/server"
        spec = importlib.util.spec_from_file_location("infocenter_sidecar_limit_fixture", server / "sidecar.py")
        sidecar = importlib.util.module_from_spec(spec)
        terminal_stub = types.ModuleType("terminal_backend")
        terminal_stub.Store, terminal_stub.mount = object, lambda *_args, **_kwargs: None
        with patch.dict(sys.modules, {"terminal_backend": terminal_stub}):
            spec.loader.exec_module(sidecar)
        self.app.request_class = sidecar.SidecarRequest
        self.app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
        body = {"chat": "mock-contact", "text": "mock-only", "attachment": {
            "name": "large-test.bin", "type": "application/octet-stream",
            "data": base64.b64encode(b"x" * (2 * 1024 * 1024)).decode(),
        }}
        self.assertGreater(len(json.dumps(body)), self.app.config["MAX_CONTENT_LENGTH"])
        result = self.client.post("/api/terminal/desktop/send/prepare", headers=self.headers, json=body)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(json.loads(self.run.call_args.kwargs["input"])["attachment"]["data"]), len(body["attachment"]["data"]))

        def terminal_limit_fixture():
            from flask import request
            return request.get_json(force=True)

        # Restore a fresh app so this limit check does not add routes after use.
        other_app = Flask("terminal-limit-fixture")
        other_app.request_class = sidecar.SidecarRequest
        other_app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
        other_app.add_url_rule("/api/terminal/non-send-test", view_func=terminal_limit_fixture, methods=["POST"])
        self.assertEqual(other_app.test_client().post("/api/terminal/non-send-test", json=body).status_code, 413)


if __name__ == "__main__":
    unittest.main()
