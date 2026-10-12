"""Native replies use current participants, a fixed filehelper and durable ids."""
import json
import unittest
import datetime as dt
import urllib.error
from unittest.mock import patch

from tests import test_infocenter as fixtures
from app.extensions import db
from app.mobile import mobile_bp
from app.models import AuthRefreshToken, InboxMessage, InboxRecipient, MessageBridgeOutbox, ProjectMember, User, utcnow
from flask_jwt_extended import create_access_token


class NativeReplyTests(unittest.TestCase):
    source_conversation = fixtures.InfoCenterProxyTests.source_conversation

    def setUp(self):
        fixtures.InfoCenterProxyTests.setUp(self)
        self.app.register_blueprint(mobile_bp, url_prefix="/api/mobile/terminal")
        self.app.config["MESSAGE_BRIDGE_TERMINAL_USER_ID"] = 1
        self.sender_patch = patch("app.message_replies.open_upstream")
        self.sender = self.sender_patch.start()
        self.sender.side_effect = lambda *_args, **_kw: fixtures.Remote(b'{"status":"submitted","available":true}')

    def tearDown(self):
        self.sender_patch.stop()
        fixtures.InfoCenterProxyTests.tearDown(self)

    def send(self, body, user=1):
        return self.client.post("/api/mobile/terminal/replies/send", json=body,
            headers={"Authorization": "Bearer " + self.tokens[user]})

    def capability(self, source, chat, uid="", user=1):
        return self.client.get("/api/mobile/terminal/replies/capabilities", query_string={
            "source": source, "chat_id": chat, "message_uid": uid},
            headers={"Authorization": "Bearer " + self.tokens[user]})

    def payload(self, source="wechat", chat="filehelper", uid=""):
        return {"id": "native-reply-request-123456", "source": source, "chat_id": chat,
                "message_uid": uid, "text": "controlled test reply"}

    def test_native_ordinary_actual_direct_participant_can_reply(self):
        chat, uid = self.source_conversation()
        self.assertTrue(self.capability("netdisk", chat, uid, user=2).json["reply_enabled"])
        body = self.payload("netdisk", chat, uid)
        self.assertEqual(self.send(body, user=2).status_code, 200)
        self.assertEqual(self.send(body, user=2).status_code, 200)
        self.assertEqual(InboxMessage.query.count(), 1)
        self.assertEqual(InboxMessage.query.one().sender_id, 2)
        self.sender.assert_not_called()

    def test_native_reply_revalidates_current_membership(self):
        chat, uid = self.source_conversation()
        InboxRecipient.query.filter_by(thread_id=10, user_id=2).delete()
        db.session.commit()
        self.assertFalse(self.capability("netdisk", chat, uid, user=2).json["reply_enabled"])
        self.assertEqual(self.send(self.payload("netdisk", chat, uid), user=2).status_code, 403)
        self.assertEqual(InboxMessage.query.count(), 0)

    def test_pending_request_rebinds_valid_same_chat_source_without_duplicate(self):
        chat, uid = self.source_conversation()
        body = self.payload("netdisk", chat, uid)
        self.assertEqual(self.send(body, user=2).status_code, 200)
        source = MessageBridgeOutbox.query.filter_by(event_uid=uid).one()
        newer = "netdisk:test:inbox:101"
        db.session.add(MessageBridgeOutbox(event_uid=newer, event_kind="inbox", source_id=101,
            payload_json=dict(source.payload_json, message_uid=newer)))
        db.session.commit()
        self.assertEqual(self.send(dict(body, message_uid=newer), user=2).status_code, 200)
        self.assertEqual(InboxMessage.query.count(), 1)
        self.assertEqual(self.send(dict(body, message_uid="netdisk:test:inbox:404"), user=2).status_code, 404)
        self.assertEqual(InboxMessage.query.count(), 1)
        InboxRecipient.query.filter_by(thread_id=10, user_id=2).delete()
        db.session.commit()
        self.assertEqual(self.send(dict(body, message_uid=newer), user=2).status_code, 403)
        self.assertEqual(InboxMessage.query.count(), 1)

    def test_native_guest_project_cannot_write(self):
        chat, uid = self.source_conversation("project_group")
        project = db.session.get(fixtures.Project, 7)
        project.creator_id = 1
        db.session.add(ProjectMember(project_id=7, user_id=2, role_project="guest"))
        db.session.commit()
        self.assertEqual(self.send(self.payload("netdisk", chat, uid), user=2).status_code, 403)
        member = ProjectMember.query.one()
        member.role_project = "user"
        db.session.commit()
        self.assertEqual(self.send(self.payload("netdisk", chat, uid), user=2).status_code, 200)

    def test_native_system_and_forged_origin_are_read_only(self):
        chat, uid = self.source_conversation("system")
        self.assertFalse(self.capability("netdisk", chat, uid).json["reply_enabled"])
        self.assertEqual(self.send(self.payload("netdisk", chat, uid)).status_code, 403)
        self.assertEqual(self.send(self.payload("netdisk", chat + "wrong", uid)).status_code, 403)
        self.sender.assert_not_called()

    def test_native_sender_and_attachments_cannot_be_spoofed(self):
        for fields in ({"sender_id": 99}, {"attachment": {}}, {"target": "person"}):
            self.assertEqual(self.send(dict(self.payload(), **fields)).status_code, 400)
        self.sender.assert_not_called()

    def test_wechat_target_is_a_literal_filehelper_only(self):
        for chat in ("person", "room@chatroom", "netdisk:test:thread:10", "filehelper "):
            self.assertFalse(self.capability("wechat", chat).json["reply_enabled"])
            self.assertEqual(self.send(self.payload(chat=chat)).status_code, 403)
        self.sender.assert_not_called()

    def test_wechat_current_configured_owner_only(self):
        self.assertFalse(self.capability("wechat", "filehelper", user=2).json["reply_enabled"])
        self.assertEqual(self.send(self.payload(), user=2).status_code, 403)
        self.app.config["MESSAGE_BRIDGE_TERMINAL_USER_ID"] = 99
        self.assertFalse(self.capability("wechat", "filehelper").json["reply_enabled"])
        self.assertEqual(self.send(self.payload()).status_code, 403)
        self.sender.assert_not_called()

    def test_readiness_is_real_and_failed_probe_disables_reply(self):
        result = self.capability("wechat", "filehelper")
        self.assertTrue(result.json["reply_enabled"])
        self.assertEqual(self.sender.call_args.args[0], "http://127.0.0.1:8767/api/terminal/desktop/send/capabilities")
        self.assertEqual(self.sender.call_args.kwargs["method"], "GET")
        self.sender.side_effect = urllib.error.URLError("unavailable")
        self.assertFalse(self.capability("wechat", "filehelper").json["reply_enabled"])

    def test_wechat_sent_receipt_keeps_key_and_fixed_target(self):
        result = self.send(self.payload())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["status"], "submitted")
        body = json.loads(self.sender.call_args.args[2])
        self.assertEqual(body, {"id": "native-reply-request-123456", "chat": "filehelper", "text": "controlled test reply"})
        self.assertEqual(self.sender.call_args.kwargs["method"], "POST")
        self.assertNotIn("private-upstream-test-credential", result.get_data(as_text=True))

    def test_timeout_is_uncertain_and_status_uses_same_request(self):
        self.sender.side_effect = TimeoutError()
        result = self.send(self.payload())
        self.assertEqual(result.status_code, 502)
        self.assertEqual(result.json["status"], "uncertain")
        self.assertEqual(result.json["id"], self.payload()["id"])
        self.sender.side_effect = lambda *_a, **_k: fixtures.Remote(b'{"status":"confirmed"}')
        result = self.client.get("/api/mobile/terminal/replies/" + self.payload()["id"] + "/status",
            headers={"Authorization": "Bearer " + self.tokens[1]})
        self.assertEqual(result.json["status"], "confirmed")
        self.assertEqual(json.loads(self.sender.call_args.args[2]), {"id": self.payload()["id"]})

    def test_empty_nul_and_invalid_request_id_are_rejected(self):
        for fields in ({"text": " "}, {"text": "x\x00y"}, {"text": "x" * 4001}, {"id": "short"}):
            self.assertEqual(self.send(dict(self.payload(), **fields)).status_code, 400)
        self.sender.assert_not_called()

    def test_account_disabled_during_lock_wait_cannot_send(self):
        from sqlalchemy.orm import Query
        chat, uid = self.source_conversation()
        original = Query.first
        changed = False
        def lock_wait(query):
            nonlocal changed
            if query._for_update_arg is not None and query.column_descriptions[0]["entity"] is User and not changed:
                changed = True
                db.session.execute(User.__table__.update().where(User.id == 2).values(status="disabled"))
                db.session.commit()
            return original(query)
        with patch.object(Query, "first", lock_wait):
            result = self.send(self.payload("netdisk", chat, uid), user=2)
        self.assertTrue(changed)
        self.assertEqual(result.status_code, 401)
        self.assertEqual(InboxMessage.query.count(), 0)

    def test_session_revoked_during_lock_wait_cannot_send(self):
        from sqlalchemy.orm import Query
        chat, uid = self.source_conversation()
        session = AuthRefreshToken(user_id=2, token_hash="reply-revoke-fixture", expires_at=utcnow()+dt.timedelta(days=1))
        db.session.add(session); db.session.commit()
        self.tokens[2] = create_access_token(identity="2", additional_claims={"auth_session": str(session.id)})
        original = Query.first
        changed = False
        def lock_wait(query):
            nonlocal changed
            if query._for_update_arg is not None and query.column_descriptions[0]["entity"] is User and not changed:
                changed = True
                db.session.execute(AuthRefreshToken.__table__.update().where(AuthRefreshToken.id == session.id).values(revoked_at=utcnow()))
                db.session.commit()
            return original(query)
        with patch.object(Query, "first", lock_wait):
            result = self.send(self.payload("netdisk", chat, uid), user=2)
        self.assertTrue(changed)
        self.assertEqual(result.status_code, 401)
        self.assertEqual(InboxMessage.query.count(), 0)

    def test_receipt_uses_unique_sender_key_and_preserves_legacy_receipts(self):
        import hashlib
        chat, uid = self.source_conversation()
        body = self.payload("netdisk", chat, uid)
        self.assertEqual(self.send(body).status_code, 200)
        receipt = MessageBridgeOutbox.query.filter_by(source_id=InboxMessage.query.one().id).one()
        self.assertEqual(receipt.reply_request_key, hashlib.sha256(("1:"+body["id"]).encode()).hexdigest())
        receipt.reply_request_key = None
        db.session.commit()
        self.assertEqual(self.send(body).status_code, 200)
        self.assertEqual(InboxMessage.query.count(), 1)

    def test_wechat_status_rechecks_owner_after_network(self):
        def demote(*_a, **_k):
            user = db.session.get(User, 1); user.role_system = "user"; db.session.commit()
            return fixtures.Remote(b'{"status":"confirmed"}')
        self.sender.side_effect = demote
        result = self.client.get("/api/mobile/terminal/replies/"+self.payload()["id"]+"/status",
            headers={"Authorization": "Bearer "+self.tokens[1]})
        self.assertEqual(result.status_code, 403)
