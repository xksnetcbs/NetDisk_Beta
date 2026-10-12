"""InfoCenter proxy security and transport tests, with no real upstream calls."""

import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from flask import Flask
from flask_jwt_extended import create_access_token
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles

from app.auth_sessions import register_auth_callbacks
from app.extensions import db, jwt
from app.infocenter import infocenter_bp
from app.models import InboxMessage, InboxRecipient, InboxThread, MessageBridgeOutbox, Project, User


@compiles(BigInteger, "sqlite")
def sqlite_bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


class Remote(io.BytesIO):
    def __init__(self, data, headers=None, status=200):
        super().__init__(data)
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}


class InfoCenterProxyTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite://",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            JWT_SECRET_KEY="test-infocenter-secret-at-least-32-characters",
            INFOCENTER_API_BASE="http://127.0.0.1:8767/api/terminal",
            INFOCENTER_API_TOKEN="private-upstream-test-credential",
        )
        db.init_app(self.app)
        jwt.init_app(self.app)
        register_auth_callbacks(jwt)
        self.app.register_blueprint(infocenter_bp, url_prefix="/api/infocenter")
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        for uid, role, active in [(1, "super_admin", True), (2, "user", True), (3, "super_admin", False)]:
            db.session.add(User(id=uid, username=f"user-{uid}", display_name=f"User {uid}",
                                password_hash="unused", role_system=role, status="active", is_activated=active))
        db.session.commit()
        self.tokens = {uid: create_access_token(identity=str(uid)) for uid in (1, 2, 3)}
        self.client = self.app.test_client()
        self.mock = patch("app.infocenter.open_upstream")
        self.upstream = self.mock.start()
        self.upstream.side_effect = lambda *_args: Remote(b'{"items":[]}')

    def tearDown(self):
        self.mock.stop()
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def get(self, path="desktop/messages", uid=1, **kwargs):
        return self.client.get("/api/infocenter/" + path,
                               headers={"Authorization": "Bearer " + self.tokens[uid]}, **kwargs)

    def post(self, path, body, uid=1):
        return self.client.post("/api/infocenter/" + path, json=body,
                                headers={"Authorization": "Bearer " + self.tokens[uid]})

    def test_anonymous_and_non_admin_never_contact_upstream(self):
        self.assertEqual(self.client.get("/api/infocenter/desktop/messages").status_code, 401)
        self.assertEqual(self.get(uid=2).status_code, 403)
        self.assertIn(self.get(uid=3).status_code, (401, 403))
        self.upstream.assert_not_called()

    def test_demotion_invalidates_an_existing_admin_token(self):
        user = db.session.get(User, 1)
        user.role_system = "user"
        db.session.commit()
        self.assertEqual(self.get().status_code, 403)
        self.upstream.assert_not_called()

    def test_proxy_uses_server_token_and_fixed_upstream_path(self):
        response = self.get("desktop/messages?chat=room&q=hello%20world&after=123")
        self.assertEqual(response.status_code, 200)
        url, token, body = self.upstream.call_args.args
        self.assertEqual(url, "http://127.0.0.1:8767/api/terminal/desktop/messages?chat=room&q=hello%20world&after=123")
        self.assertEqual(token, "private-upstream-test-credential")
        self.assertIsNone(body)
        self.assertNotIn(token.encode(), response.data)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_unknown_paths_methods_and_query_tokens_are_blocked(self):
        for path in ("desktop/../../llm", "desktop/llm", "desktop/messages/1/secret", "terminal/llm", "other/messages"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status_code, 404)
        self.assertEqual(self.post("desktop/messages", {}).status_code, 405)
        self.assertEqual(self.get("desktop/send/prepare").status_code, 405)
        self.assertEqual(self.get("desktop/messages?token=browser-token").status_code, 400)
        self.upstream.assert_not_called()

    def test_read_state_and_pending_cursor_are_preserved(self):
        self.upstream.side_effect = lambda *_: Remote(b'{"pending":true}', status=202)
        result = self.post("terminal/conversations/read", {"chat_id": "room", "through_uid": "new-uid"})
        self.assertEqual(result.status_code, 202)
        self.assertTrue(result.json["pending"])
        self.assertEqual(json.loads(self.upstream.call_args.args[2])["through_uid"], "new-uid")

    def test_invalid_query_bytes_are_rejected_without_contacting_upstream(self):
        result = self.get(environ_overrides={"QUERY_STRING": "\xff"})
        self.assertEqual(result.status_code, 400)
        self.upstream.assert_not_called()

    def test_proxy_post_supports_flask_30_read_only_request_limit(self):
        request_class = self.app.request_class
        legacy_limit = property(request_class.max_content_length.fget)
        with patch.object(request_class, "max_content_length", legacy_limit):
            result = self.post("terminal/conversations/read", {"chat_id": "room", "through_uid": "message"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(json.loads(self.upstream.call_args.args[2]), {"chat_id": "room", "through_uid": "message"})

    def test_send_json_is_proxied_without_executing_real_send(self):
        body = {"id": "test-request-identifier", "chat": "room", "text": "test"}
        self.assertEqual(self.post("desktop/send/prepare", body).status_code, 200)
        self.assertEqual(json.loads(self.upstream.call_args.args[2]), body)

    def test_json_validation_and_request_limit(self):
        headers = {"Authorization": "Bearer " + self.tokens[1]}
        self.assertEqual(self.client.post("/api/infocenter/desktop/send/prepare", data="text", headers=headers).status_code, 415)
        self.assertEqual(self.client.post("/api/infocenter/desktop/send/prepare", json=[], headers=headers).status_code, 400)
        self.app.config["MAX_CONTENT_LENGTH"] = 5
        self.assertEqual(self.post("desktop/send/prepare", {"text": "larger than host limit"}).status_code, 200)
        with patch("app.infocenter.MAX_REQUEST_BYTES", 10):
            self.assertEqual(self.post("desktop/send/prepare", {"text": "too large"}).status_code, 413)

    def test_binary_stream_keeps_download_headers_but_no_cookie(self):
        remote = Remote(b"abcdef", {"Content-Type": "application/octet-stream", "Content-Length": "6",
                                    "Content-Disposition": 'attachment; filename="file.txt"', "Set-Cookie": "upstream=private"})
        self.upstream.side_effect = None
        self.upstream.return_value = remote
        result = self.get("desktop/messages/12/file")
        self.assertEqual(result.data, b"abcdef")
        self.assertIn("file.txt", result.headers["Content-Disposition"])
        self.assertNotIn("Set-Cookie", result.headers)
        self.assertTrue(remote.closed)

    def test_media_range_response_and_head_are_supported(self):
        self.upstream.side_effect = lambda *_: Remote(b"bc", {"Content-Type": "audio/wav", "Content-Range": "bytes 1-2/6"}, status=206)
        result = self.get("desktop/messages/12/media")
        self.assertEqual(result.status_code, 206)
        self.assertEqual(result.headers["Content-Range"], "bytes 1-2/6")
        result = self.client.head("/api/infocenter/desktop/messages/12/file",
                                  headers={"Authorization": "Bearer " + self.tokens[1]})
        self.assertEqual(result.data, b"")

    def test_upstream_auth_failure_does_not_revoke_netdisk_session(self):
        self.upstream.side_effect = urllib.error.HTTPError("private", 401, "failed", {}, io.BytesIO())
        self.assertEqual(self.get().status_code, 502)

    def test_redirect_network_errors_and_missing_config(self):
        self.upstream.side_effect = urllib.error.HTTPError("private", 302, "redirect", {}, io.BytesIO())
        self.assertEqual(self.get().status_code, 502)
        self.upstream.side_effect = urllib.error.URLError("unavailable")
        self.assertEqual(self.get().status_code, 502)
        self.app.config["INFOCENTER_API_TOKEN"] = ""
        self.assertEqual(self.get().status_code, 503)

    def test_upstream_json_cannot_echo_server_credentials(self):
        self.upstream.side_effect = lambda *_: Remote(b'{"error":"private-upstream-test-credential"}')
        response = self.get()
        self.assertEqual(response.json["error"], "[redacted]")

    def source_conversation(self, kind="direct", participant=True):
        self.app.config.update(MESSAGE_BRIDGE_ENABLED=True, MESSAGE_BRIDGE_INSTANCE_ID="test")
        self.app.extensions["message_bridge"] = True
        thread = InboxThread(id=10, type=kind, subject="project:7" if kind == "project_group" else "Test thread", created_by=2)
        db.session.add(thread)
        db.session.add(InboxRecipient(thread_id=10, user_id=2))
        if participant:
            db.session.add(InboxRecipient(thread_id=10, user_id=1))
        if kind == "project_group":
            db.session.add(Project(id=7, name="Test project", key="test-project", creator_id=2, status="active"))
        chat = "netdisk:test:project:7@chatroom" if kind == "project_group" else "netdisk:test:thread:10"
        uid = "netdisk:test:inbox:100"
        db.session.add(MessageBridgeOutbox(event_uid=uid, event_kind="inbox", source_id=100, payload_json={
            "source": "netdisk", "instance_id": "test", "chat_id": chat, "thread_id": 10,
            "thread_type": kind, "project_id": 7 if kind == "project_group" else None,
        }))
        db.session.commit()
        return chat, uid

    def reply(self, chat, uid, user=1, **extra):
        return self.post("netdisk/conversations/" + chat + "/send", {
            "id": "safe-reply-request-123456", "text": "a local reply", "message_uid": uid, **extra,
        }, uid=user)

    def test_local_direct_reply_has_authenticated_sender_and_atomic_outbox(self):
        chat, uid = self.source_conversation()
        response = self.reply(chat, uid, sender_id=999)
        self.assertEqual(response.status_code, 200)
        message = InboxMessage.query.one()
        self.assertEqual(message.sender_id, 1)
        self.assertEqual(message.content_md, "a local reply")
        event = MessageBridgeOutbox.query.filter_by(source_id=message.id).one()
        self.assertEqual(event.payload_json["reply_request_id"], "safe-reply-request-123456")
        self.assertEqual(self.reply(chat, uid).status_code, 200)
        self.assertEqual(InboxMessage.query.count(), 1)
        self.assertEqual(self.reply(chat, uid, text="changed payload").status_code, 409)
        self.upstream.assert_not_called()

    def test_local_project_reply_uses_existing_group_model(self):
        chat, uid = self.source_conversation("project_group", participant=False)
        result = self.reply(chat, uid)
        self.assertEqual(result.status_code, 200)
        message = InboxMessage.query.one()
        self.assertEqual(message.thread_id, 10)
        self.assertEqual(message.sender_id, 1)
        self.assertEqual(MessageBridgeOutbox.query.filter_by(source_id=message.id).one().payload_json["project_id"], 7)
        self.upstream.assert_not_called()

    def test_nonparticipant_admin_and_ordinary_user_cannot_reply(self):
        chat, uid = self.source_conversation(participant=False)
        self.assertEqual(self.reply(chat, uid).status_code, 403)
        self.assertEqual(self.reply(chat, uid, user=2).status_code, 403)
        self.assertEqual(InboxMessage.query.count(), 0)
        self.upstream.assert_not_called()

    def test_system_notification_and_mismatched_source_are_read_only(self):
        chat, uid = self.source_conversation("system")
        self.assertEqual(self.reply(chat, uid).status_code, 403)
        self.assertEqual(self.reply("netdisk:test:thread:999", uid).status_code, 403)
        self.assertEqual(InboxMessage.query.count(), 0)
        self.upstream.assert_not_called()

    def test_local_reply_rejects_malformed_body_and_source(self):
        self.assertEqual(self.post("netdisk/conversations/chat/send", ["invalid"]).status_code, 400)
        chat, uid = self.source_conversation()
        self.assertEqual(self.reply(chat, {"unexpected": "object"}).status_code, 400)
        self.assertEqual(InboxMessage.query.count(), 0)
        self.upstream.assert_not_called()

    def test_upstream_validation_preserves_useful_error_without_credentials(self):
        data = json.dumps({"error": "操作超时，不要重复发送 private-upstream-test-credential"}).encode()
        self.upstream.side_effect = urllib.error.HTTPError("private", 400, "bad request", {}, io.BytesIO(data))
        result = self.get()
        self.assertEqual(result.status_code, 400)
        self.assertIn("不要重复发送", result.json["error"])
        self.assertNotIn("private-upstream-test-credential", result.json["error"])


if __name__ == "__main__":
    unittest.main()
