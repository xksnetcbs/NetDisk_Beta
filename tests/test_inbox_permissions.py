"""Legacy Inbox authorization regressions using in-memory SQLite only."""

import unittest

from flask import Flask
from flask_jwt_extended import create_access_token
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles

from app.api import add_project_system_message, api_bp
from app.auth_sessions import register_auth_callbacks
from app.extensions import db, jwt
from app.message_bridge import can_read_netdisk_event, register_message_bridge
from app.models import (
    InboxMessage, InboxRecipient, InboxThread, MessageBridgeOutbox, Notification,
    Project, ProjectMember, ProjectSettings, User,
)


@compiles(BigInteger, "sqlite")
def sqlite_integer(_type, _compiler, **_kwargs):
    return "INTEGER"


class InboxPermissionTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite://",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            JWT_SECRET_KEY="offline-inbox-jwt-fixture-at-least-32-characters",
            MESSAGE_BRIDGE_ENABLED=True, MESSAGE_BRIDGE_INSTANCE_ID="inbox-fixture",
            MESSAGE_BRIDGE_INLINE_DELIVERY=False, READABLE_STORAGE_ENABLED=False,
        )
        db.init_app(self.app)
        jwt.init_app(self.app)
        register_auth_callbacks(jwt)
        register_message_bridge(self.app)
        self.app.register_blueprint(api_bp, url_prefix="/api")
        self.context = self.app.app_context()
        self.context.push()
        for table in db.metadata.tables.values():
            table.dialect_options["sqlite"]["autoincrement"] = True
        db.create_all()
        for user_id, role, status, active in (
            (1,"super_admin","active",True), (2,"user","active",True),
            (3,"user","active",True), (4,"user","disabled",True),
            (5,"user","active",False), (6,"user","active",True),
            (7,"user","active",True),
        ):
            db.session.add(User(id=user_id,username=f"inbox-{user_id}",display_name=f"User {user_id}",
                                password_hash="unused",role_system=role,status=status,is_activated=active))
        db.session.add(Project(id=10,name="Current project",key="INBOX_CURRENT",creator_id=6))
        db.session.add(Project(id=20,name="Public project",key="INBOX_PUBLIC",creator_id=3))
        db.session.add_all([
            ProjectMember(project_id=10,user_id=2,role_project="user"),
            ProjectMember(project_id=10,user_id=6,role_project="creator"),
            ProjectMember(project_id=10,user_id=7,role_project="guest"),
            ProjectSettings(project_id=20,guest_visible=True,task_workflow=[]),
        ])
        db.session.commit()
        self.tokens={user_id:create_access_token(identity=str(user_id)) for user_id in (1,2,3,6,7)}
        self.client=self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def request(self, method, path="", user_id=2, body=None):
        return self.client.open("/api/inbox/threads"+path,method=method,json=body,
                                headers={"Authorization":"Bearer "+self.tokens[user_id]})

    def seed_thread(self, kind, recipients, subject="Offline", sender=2):
        thread=InboxThread(type=kind,subject=subject,created_by=1)
        db.session.add(thread)
        db.session.flush()
        for user_id in recipients:
            db.session.add(InboxRecipient(thread_id=thread.id,user_id=user_id))
        db.session.add(InboxMessage(thread_id=thread.id,sender_id=sender,content_md="Private fixture content"))
        db.session.commit()
        return thread

    def test_clients_cannot_forge_system_or_project_group_even_as_super_admin(self):
        for user_id in (1,2):
            for kind in ("system","project_group"):
                with self.subTest(user_id=user_id,kind=kind):
                    response=self.request("POST",user_id=user_id,body={"type":kind,"recipients":[3],
                                                                        "subject":"project:20","content_md":"forged"})
                    self.assertEqual(response.status_code,403)
        self.assertEqual(InboxThread.query.count(),0)
        self.assertEqual(InboxMessage.query.count(),0)
        self.assertEqual(MessageBridgeOutbox.query.count(),0)
        self.assertEqual(Notification.query.count(),0)

    def test_recipient_ids_require_active_real_users_and_integer_values(self):
        for recipients in ([],"3",[None],[True],[3.0],["three"],[0],[-3],[999],[4],[5],["9"*5000],[3,999]):
            with self.subTest(recipients=str(recipients)[:40]):
                response=self.request("POST",body={"type":"direct","recipients":recipients,"content_md":"hello"})
                self.assertEqual(response.status_code,400)
        self.assertEqual(InboxThread.query.count(),0)
        self.assertEqual(MessageBridgeOutbox.query.count(),0)

    def test_direct_participants_send_read_and_self_duplicates_are_removed(self):
        response=self.request("POST",body={"recipients":[2,"2",3,"3",3],"subject":"Direct fixture","content_md":"hello"})
        self.assertEqual(response.status_code,200)
        thread_id=response.json["data"]["thread"]["id"]
        self.assertEqual({row.user_id for row in InboxRecipient.query.filter_by(thread_id=thread_id)},{2,3})
        self.assertEqual(InboxRecipient.query.filter_by(thread_id=thread_id).count(),2)
        self.assertEqual(Notification.query.count(),1)
        outbox=MessageBridgeOutbox.query.first()
        self.assertEqual(outbox.payload_json["thread_type"],"direct")
        self.assertEqual(outbox.payload_json["sender_user_id"],2)
        self.assertIsNone(outbox.payload_json["project_id"])
        self.assertEqual(self.request("POST",f"/{thread_id}/messages",user_id=3,body={"content_md":"reply"}).status_code,200)
        response=self.request("GET",f"/{thread_id}/messages")
        self.assertEqual([row["content_md"] for row in response.json["data"]["items"]],["hello","reply"])
        self.assertEqual(self.request("POST",f"/{thread_id}/read",user_id=3).status_code,200)
        self.assertIsNotNone(InboxRecipient.query.filter_by(thread_id=thread_id,user_id=3).first().last_read_at)

    def test_nonparticipant_super_admin_cannot_send_direct_messages(self):
        thread=self.seed_thread("direct",[2,3])
        count=InboxMessage.query.count()
        self.assertEqual(self.request("POST",f"/{thread.id}/messages",user_id=1,body={"content_md":"spectator"}).status_code,403)
        self.assertEqual(self.request("POST",f"/{thread.id}/messages",user_id=6,body={"content_md":"spectator"}).status_code,403)
        self.assertEqual(InboxMessage.query.count(),count)
        self.assertEqual(self.request("GET",f"/{thread.id}/messages",user_id=6).status_code,403)
        self.assertEqual(self.request("POST",f"/{thread.id}/read",user_id=6).status_code,403)

    def test_system_server_records_are_readable_but_clients_cannot_append(self):
        thread=self.seed_thread("system",[2],subject="Server notice",sender=0)
        response=self.request("GET",f"/{thread.id}/messages")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json["data"]["items"][0]["sender_name"],"Server")
        self.assertEqual(self.request("POST",f"/{thread.id}/read").status_code,200)
        for user_id in (1,2):
            self.assertEqual(self.request("POST",f"/{thread.id}/messages",user_id=user_id,body={"content_md":"fake Server"}).status_code,403)
        self.assertEqual(InboxMessage.query.count(),1)
        self.assertEqual(MessageBridgeOutbox.query.first().payload_json["sender_name"],"Server")

    def test_departed_project_member_cannot_list_read_mark_or_send_via_stale_recipient(self):
        thread=self.seed_thread("project_group",[2,6],subject="project:10")
        uid=MessageBridgeOutbox.query.first().event_uid
        self.assertTrue(can_read_netdisk_event(uid,2))
        db.session.delete(ProjectMember.query.filter_by(project_id=10,user_id=2).first())
        db.session.commit()
        self.assertIsNotNone(InboxRecipient.query.filter_by(thread_id=thread.id,user_id=2).first())
        self.assertFalse(can_read_netdisk_event(uid,2))
        listed=self.request("GET").json["data"]["items"]
        self.assertNotIn(thread.id,{item["id"] for item in listed})
        for method,path,body in (("GET","messages",None),("POST","read",None),("POST","messages",{"content_md":"after exit"})):
            self.assertEqual(self.request(method,f"/{thread.id}/{path}",body=body).status_code,403)
        self.assertIsNone(InboxRecipient.query.filter_by(thread_id=thread.id,user_id=2).first().last_read_at)
        self.assertEqual(InboxMessage.query.count(),1)

    def test_public_project_visibility_does_not_grant_stale_inbox_membership(self):
        thread=self.seed_thread("project_group",[2],subject="project:20")
        self.assertFalse(can_read_netdisk_event(MessageBridgeOutbox.query.first().event_uid,2))
        self.assertEqual(self.request("GET").json["data"]["items"],[])
        self.assertEqual(self.request("GET",f"/{thread.id}/messages").status_code,403)
        self.assertEqual(self.request("POST",f"/{thread.id}/read").status_code,403)
        self.assertEqual(self.request("POST",f"/{thread.id}/messages",body={"content_md":"unrelated"}).status_code,403)

    def test_current_project_roles_and_server_helpers_remain_usable(self):
        thread_id=add_project_system_message(10,"Trusted project system message",1)
        db.session.commit()
        self.assertEqual(InboxMessage.query.first().sender_id,0)
        self.assertEqual(MessageBridgeOutbox.query.first().payload_json["thread_type"],"project_group")
        for user_id in (2,6,1):
            self.assertEqual(self.request("POST",f"/{thread_id}/messages",user_id=user_id,body={"content_md":f"Allowed {user_id}"}).status_code,200)
        self.assertIsNone(InboxRecipient.query.filter_by(thread_id=thread_id,user_id=1).first())
        self.assertEqual(self.request("GET",f"/{thread_id}/messages",user_id=7).status_code,200)
        self.assertEqual(self.request("POST",f"/{thread_id}/messages",user_id=7,body={"content_md":"guest write"}).status_code,403)
        self.assertEqual(InboxMessage.query.count(),4)


if __name__ == "__main__":
    unittest.main()
