"""Offline outbox, capture compatibility and canonical unread regressions."""

import datetime as dt
import contextlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from flask import Flask
from flask_jwt_extended import create_access_token
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles

from app.extensions import db, jwt
from app.message_bridge import (
    backfill_outbox, can_read_netdisk_event, deliver_pending, event_uid,
    register_message_bridge, sync_terminal_reads,
)
from app.models import (
    InboxMessage, InboxRecipient, InboxThread, MessageBridgeOutbox, Notification,
    Project, ProjectMember, Task, TaskComment, User, utcnow,
)


@compiles(BigInteger, "sqlite")
def sqlite_big_integer(_type, _compiler, **_kwargs):
    return "INTEGER"


CAPTURE_SCHEMA = """
CREATE TABLE messages(
 message_uid TEXT PRIMARY KEY,chat_username TEXT NOT NULL,chat_display_name TEXT,
 message_table TEXT NOT NULL,source_message_db TEXT NOT NULL,local_id INTEGER NOT NULL,
 server_id INTEGER,local_type INTEGER,base_type INTEGER,app_subtype INTEGER,type_label TEXT,
 sort_seq INTEGER,real_sender_id INTEGER,create_time INTEGER,status INTEGER,upload_status INTEGER,
 download_status INTEGER,server_seq INTEGER,origin_source INTEGER,source TEXT,message_content TEXT,
 compress_content TEXT,content_sha256 TEXT NOT NULL,packed_info_sha256 TEXT,ingested_at TEXT NOT NULL);
CREATE TABLE chats(username TEXT PRIMARY KEY,display_name TEXT,is_group INTEGER NOT NULL DEFAULT 0,
 session_type INTEGER,last_timestamp INTEGER,sort_timestamp INTEGER,message_table TEXT,
 source_message_db TEXT,updated_at TEXT NOT NULL);
"""

TERMINAL_SCHEMA = """
CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,source TEXT NOT NULL,source_key TEXT NOT NULL,
 title TEXT NOT NULL,body TEXT NOT NULL,chat TEXT NOT NULL DEFAULT '',occurred_at INTEGER NOT NULL,
 created_at INTEGER NOT NULL,is_read INTEGER NOT NULL DEFAULT 0,notify INTEGER NOT NULL DEFAULT 1,
 payload TEXT NOT NULL DEFAULT '{}',llm_status TEXT NOT NULL DEFAULT 'skip',llm_attempts INTEGER NOT NULL DEFAULT 0,
 llm_retry_at INTEGER NOT NULL DEFAULT 0,is_outgoing INTEGER NOT NULL DEFAULT 0,UNIQUE(source,source_key));
CREATE TABLE directory(username TEXT PRIMARY KEY,name TEXT,wx_remark TEXT,note TEXT,muted INTEGER);
"""


@contextlib.contextmanager
def sqlite_connection(path):
    with contextlib.closing(sqlite3.connect(path)) as connection:
        with connection:
            yield connection


class MessageBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="netdisk-bridge-test-")
        self.root = Path(self.temporary.name)
        self.capture = self.root / "memory.sqlite"
        self.terminal = self.root / "terminal.sqlite"
        with sqlite_connection(self.capture) as connection:
            connection.executescript(CAPTURE_SCHEMA)
        with sqlite_connection(self.terminal) as connection:
            connection.executescript(TERMINAL_SCHEMA)
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,SQLALCHEMY_DATABASE_URI="sqlite:///" + str(self.root / "source.sqlite"),
            SQLALCHEMY_TRACK_MODIFICATIONS=False,MESSAGE_BRIDGE_ENABLED=True,
            MESSAGE_BRIDGE_INSTANCE_ID="fixture",MESSAGE_BRIDGE_CAPTURE_DB=str(self.capture),
            MESSAGE_BRIDGE_TERMINAL_DB=str(self.terminal),MESSAGE_BRIDGE_TERMINAL_USER_ID=1,
            MESSAGE_BRIDGE_INLINE_DELIVERY=True,
        )
        db.init_app(self.app)
        register_message_bridge(self.app)
        self.context = self.app.app_context()
        self.context.push()
        for table in db.metadata.tables.values():
            table.dialect_options["sqlite"]["autoincrement"] = True
        db.create_all()
        for user_id, name, role in ((1,"storage_admin","super_admin"),(2,"member","user"),(3,"outside","user")):
            db.session.add(User(id=user_id,username=name,display_name=name,password_hash="unused",role_system=role,status="active",is_activated=True))
        db.session.add(Project(id=10,name="群项目",key="GROUP",creator_id=1))
        db.session.add(ProjectMember(project_id=10,user_id=2,role_project="user"))
        db.session.commit()

        @self.app.post("/emit")
        def emit():
            self.new_thread("direct", [1, 2], content="request-committed message")
            return {"ok":True}

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.temporary.cleanup()

    def new_thread(self, kind, recipients, content="hello", subject=None, commit=True):
        thread = InboxThread(type=kind,subject=subject or ("project:10" if kind=="project_group" else "测试会话"),created_by=1)
        db.session.add(thread)
        db.session.flush()
        for user_id in recipients:
            db.session.add(InboxRecipient(thread_id=int(thread.id),user_id=user_id))
        message = InboxMessage(thread_id=int(thread.id),sender_id=2,content_md=content)
        db.session.add(message)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return thread, message

    def rows(self, path, sql="SELECT * FROM messages", args=()):
        with sqlite_connection(path) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql,args)]

    def test_outbox_is_atomic_with_source_commit_and_rollback(self):
        _, message = self.new_thread("direct",[1,2],commit=False)
        self.assertEqual(MessageBridgeOutbox.query.count(),1)
        self.assertEqual(MessageBridgeOutbox.query.first().event_uid,event_uid("inbox",message.id))
        self.assertEqual(self.rows(self.capture),[])
        db.session.rollback()
        self.assertEqual(InboxMessage.query.count(),0)
        self.assertEqual(MessageBridgeOutbox.query.count(),0)
        self.assertEqual(deliver_pending()["delivered"],0)

    def test_group_private_and_system_chat_namespace_and_recipient_scope(self):
        expected = []
        for kind, recipients in (("project_group",[1,2]),("direct",[1,2]),("system",[1])):
            thread,message = self.new_thread(kind,recipients)
            expected.append((thread,message))
        self.assertEqual(deliver_pending(),{"delivered":3,"failed":0})
        rows = self.rows(self.capture)
        self.assertEqual(len(rows),3)
        self.assertEqual(len({row["message_uid"] for row in rows}),3)
        self.assertTrue(rows[0]["chat_username"].endswith("project:10@chatroom"))
        self.assertTrue(rows[1]["chat_username"].endswith(f"thread:{expected[1][0].id}"))
        self.assertTrue(rows[2]["chat_username"].endswith(f"thread:{expected[2][0].id}"))
        self.assertTrue(all(row["source"]=="netdisk" and row["source_message_db"]=="" and row["real_sender_id"]==0 for row in rows))
        metadata = self.rows(self.capture,"SELECT * FROM netdisk_message_meta")
        self.assertEqual(json.loads(metadata[2]["recipient_ids"]),[1])
        self.assertEqual(metadata[2]["sender_name"],"Server")
        self.assertEqual(len(self.rows(self.terminal,"SELECT * FROM messages WHERE is_outgoing=0")),3)

    def test_stable_uid_retry_backfill_and_compat_alias_prevent_duplicate_views(self):
        _,message = self.new_thread("direct",[1,2])
        uid = event_uid("inbox",message.id)
        self.assertEqual(backfill_outbox(),0)
        self.assertEqual(deliver_pending()["delivered"],1)
        outbox = MessageBridgeOutbox.query.first()
        outbox.delivered_at = None
        db.session.commit()
        self.assertEqual(deliver_pending(retry_now=True)["delivered"],1)
        self.assertEqual(len(self.rows(self.capture)),1)
        visible = self.rows(self.terminal,"SELECT * FROM messages WHERE is_outgoing=0")
        self.assertEqual([(row["source"],row["source_key"]) for row in visible],[("netdisk",uid)])
        with sqlite_connection(self.terminal) as terminal:
            terminal.execute("INSERT OR IGNORE INTO messages(source,source_key,title,body,occurred_at,created_at) VALUES(?,?,?,?,?,?)",("wechat",uid,"legacy collector","duplicate",1,1))
        alias = self.rows(self.terminal,"SELECT * FROM messages WHERE source='wechat'")[0]
        self.assertEqual((alias["is_outgoing"],alias["is_read"],alias["notify"]),(1,1,0))
        self.assertEqual(len(self.rows(self.terminal,"SELECT * FROM messages WHERE is_outgoing=0")),1)

    def test_terminal_published_capture_failure_retains_outbox_and_retry_is_idempotent(self):
        self.new_thread("direct",[1,2])
        self.app.config["MESSAGE_BRIDGE_CAPTURE_DB"] = str(self.root / "nonexistent.sqlite")
        self.assertEqual(deliver_pending(),{"delivered":0,"failed":1})
        self.assertFalse((self.root / "nonexistent.sqlite").exists())
        self.assertEqual(len(self.rows(self.terminal,"SELECT * FROM messages WHERE is_outgoing=0")),1)
        row = MessageBridgeOutbox.query.first()
        self.assertIsNone(row.delivered_at)
        self.assertEqual(row.last_error,"OperationalError")
        self.assertIsNotNone(row.next_attempt_at)
        self.app.config["MESSAGE_BRIDGE_CAPTURE_DB"] = str(self.capture)
        self.assertEqual(deliver_pending(retry_now=True),{"delivered":1,"failed":0})
        self.assertEqual(len(self.rows(self.capture)),1)
        self.assertEqual(len(self.rows(self.terminal,"SELECT * FROM messages WHERE is_outgoing=0")),1)

    def test_terminal_failure_leaves_both_sources_retryable_and_capture_unwritten(self):
        self.new_thread("direct",[1,2])
        self.app.config["MESSAGE_BRIDGE_TERMINAL_DB"] = str(self.root / "missing-terminal.sqlite")
        self.assertEqual(deliver_pending(),{"delivered":0,"failed":1})
        self.assertEqual(self.rows(self.capture),[])
        self.app.config["MESSAGE_BRIDGE_TERMINAL_DB"] = str(self.terminal)
        self.assertEqual(deliver_pending(retry_now=True),{"delivered":1,"failed":0})

    def test_notification_canonical_dedup_and_admission_action_payload(self):
        thread,message = self.new_thread("system",[1],content="新用户等待审核",subject="准入审核",commit=False)
        notification = Notification(user_id=1,type="system",title="准入审核",content=message.content_md,link_url="/admin",meta_json={"user_id":3})
        db.session.add(notification)
        db.session.add(Notification(user_id=1,type="inbox_message",title="新站内信",
            meta_json={"thread_id":int(thread.id),"message_id":int(message.id)}))
        db.session.add(Notification(user_id=3,type="user_activated",title="管理员已通过审核",link_url="/login"))
        db.session.commit()
        # The message was flushed before its paired notification; backfill
        # enriches that still-pending canonical payload with its action link.
        self.assertEqual(MessageBridgeOutbox.query.count(),2)
        payloads = [row.payload_json for row in MessageBridgeOutbox.query.order_by(MessageBridgeOutbox.id)]
        self.assertEqual(payloads[0]["link_url"],"/admin")
        self.assertEqual(payloads[0]["user_id"],3)
        self.assertEqual(payloads[1]["recipient_ids"],[3])
        self.assertIn("system:user:3",payloads[1]["chat_id"])
        self.assertEqual(payloads[1]["link_url"],"/login")
        self.assertEqual(deliver_pending()["delivered"],2)

    def new_task(self):
        task = Task(project_id=10,title="评论桥接任务",status="todo",reporter_id=1)
        db.session.add(task)
        db.session.commit()
        return task

    def test_task_comment_full_text_uses_project_chat_sender_and_task_link(self):
        thread, _ = self.new_thread("project_group", [1, 2])
        task = self.new_task()
        content = "任务评论完整文本\n**Markdown** @{1}\n" + "保留全文。" * 5000
        comment = TaskComment(task_id=task.id,user_id=2,content_md=content)
        db.session.add(comment)
        db.session.commit()
        event = MessageBridgeOutbox.query.filter_by(event_kind="task_comment",source_id=comment.id).one()
        payload = event.payload_json
        self.assertEqual(event.event_uid,event_uid("task_comment",comment.id))
        self.assertEqual((payload["chat_id"],payload["thread_type"],payload["thread_id"]),
                         ("netdisk:fixture:project:10@chatroom","project_group",thread.id))
        self.assertEqual((payload["task_id"],payload["comment_id"],payload["sender_user_id"],payload["sender_name"]),
                         (task.id,comment.id,2,"member"))
        self.assertEqual(payload["recipient_ids"],[1,2])
        self.assertEqual(payload["link_url"],f"/projects/10?tab=tasks&task={task.id}")
        self.assertEqual(payload["content"],content)
        deliver_pending()
        capture = self.rows(self.capture,"SELECT * FROM messages WHERE message_uid='" + event.event_uid + "'")[0]
        terminal = self.rows(self.terminal,"SELECT * FROM messages WHERE source='netdisk' AND source_key='" + event.event_uid + "'")[0]
        self.assertTrue(capture["message_content"].endswith(content))
        self.assertEqual(terminal["body"],content)
        self.assertTrue(can_read_netdisk_event(event.event_uid,2))
        db.session.delete(ProjectMember.query.filter_by(project_id=10,user_id=2).one())
        db.session.commit()
        self.assertFalse(can_read_netdisk_event(event.event_uid,2))

    def test_task_comment_outbox_rolls_back_with_source_without_external_writes(self):
        task = self.new_task()
        comment = TaskComment(task_id=task.id,user_id=2,content_md="rollback comment")
        db.session.add(comment)
        db.session.flush()
        self.assertEqual(MessageBridgeOutbox.query.filter_by(event_kind="task_comment").count(),1)
        db.session.rollback()
        self.assertEqual(TaskComment.query.count(),0)
        self.assertEqual(MessageBridgeOutbox.query.count(),0)
        self.assertEqual(self.rows(self.capture),[])
        self.assertEqual(self.rows(self.terminal),[])

    def test_task_comment_keyset_backfill_is_idempotent_quiet_and_needs_no_inbox_thread(self):
        task = self.new_task()
        self.app.config["MESSAGE_BRIDGE_ENABLED"] = False
        for number in range(423):
            db.session.add(TaskComment(task_id=task.id,user_id=2,content_md=f"Historical task comment {number}",
                                       created_at=utcnow()-dt.timedelta(days=2)))
        db.session.commit()
        self.app.config["MESSAGE_BRIDGE_ENABLED"] = True
        with patch("sqlalchemy.orm.Query.yield_per",side_effect=AssertionError("historical results must be buffered")):
            self.assertEqual(backfill_outbox(),423)
            self.assertEqual(backfill_outbox(),0)
        events = MessageBridgeOutbox.query.filter_by(event_kind="task_comment").all()
        self.assertEqual(len({row.event_uid for row in events}),423)
        self.assertTrue(all(row.payload_json["thread_id"] is None for row in events))
        self.assertEqual(self.rows(self.capture),[])
        self.assertEqual(deliver_pending(limit=1000)["delivered"],423)
        visible = self.rows(self.terminal,"SELECT * FROM messages WHERE source='netdisk'")
        self.assertTrue(all((row["is_read"],row["notify"],row["llm_status"])==(1,0,"skip") for row in visible))

    def test_real_task_comment_api_keeps_mention_system_notification_without_thread_id(self):
        from app.api import api_bp
        self.app.config.update(JWT_SECRET_KEY="bridge-test-secret-at-least-32-characters",MESSAGE_BRIDGE_INLINE_DELIVERY=False)
        jwt.init_app(self.app)
        self.app.register_blueprint(api_bp,url_prefix="/api")
        task = self.new_task()
        token = create_access_token(identity="2")
        response = self.app.test_client().post(f"/api/tasks/{task.id}/comments",
            headers={"Authorization":"Bearer "+token},json={"content_md":"A full task comment mentioning @{1}"})
        self.assertEqual(response.status_code,200)
        comment = TaskComment.query.one()
        notification = Notification.query.filter_by(type="mention").one()
        self.assertNotIn("thread_id",notification.meta_json)
        events = MessageBridgeOutbox.query.order_by(MessageBridgeOutbox.id).all()
        self.assertEqual({(row.event_kind,row.source_id) for row in events},{("task_comment",comment.id),("notification",notification.id)})
        notice = next(row.payload_json for row in events if row.event_kind=="notification")
        self.assertEqual((notice["thread_type"],notice["recipient_ids"]),("system",[1]))
        self.assertEqual(notice["link_url"],f"/projects/10?tab=tasks&task={task.id}")
        self.assertEqual(self.rows(self.capture),[])

    def test_inbox_mention_dedup_requires_existing_canonical_thread_and_message(self):
        thread, message = self.new_thread("direct",[1,2])
        notices = [
            Notification(user_id=1,type="mention",title="canonical mention",meta_json={"thread_id":thread.id}),
            Notification(user_id=1,type="inbox_message",title="canonical inbox",meta_json={"thread_id":thread.id,"message_id":message.id}),
            Notification(user_id=1,type="mention",title="missing thread",meta_json={"thread_id":999999}),
            Notification(user_id=1,type="mention",title="missing message",meta_json={"thread_id":thread.id,"message_id":999999}),
            Notification(user_id=1,type="inbox_message",title="no canonical metadata"),
        ]
        db.session.add_all(notices)
        db.session.commit()
        source_ids = {row.source_id for row in MessageBridgeOutbox.query.filter_by(event_kind="notification")}
        self.assertEqual(source_ids,{notice.id for notice in notices[2:]})
        self.assertEqual(MessageBridgeOutbox.query.filter_by(event_kind="inbox").count(),1)

    def test_same_flush_canonical_notification_enriches_single_pending_inbox_outbox(self):
        thread = InboxThread(type="direct",subject="same-flush thread",created_by=2)
        db.session.add(thread)
        db.session.flush()
        db.session.add_all([InboxRecipient(thread_id=thread.id,user_id=1),InboxRecipient(thread_id=thread.id,user_id=2)])
        message = InboxMessage(thread_id=thread.id,sender_id=2,content_md="single canonical message")
        notification = Notification(user_id=1,type="inbox_message",title="你收到一条新站内信",meta_json={"thread_id":thread.id})
        db.session.add_all([message,notification])
        db.session.commit()
        outbox = MessageBridgeOutbox.query.one()
        self.assertEqual((outbox.event_kind,outbox.source_id),("inbox",message.id))
        self.assertEqual(outbox.event_uid,event_uid("inbox",message.id))
        self.assertEqual(deliver_pending()["delivered"],1)
        self.assertEqual(len(self.rows(self.capture)),1)

    def test_disabled_bridge_is_external_write_free_and_backfill_recovers_history(self):
        self.app.config["MESSAGE_BRIDGE_ENABLED"] = False
        self.new_thread("project_group",[1,2])
        self.assertEqual(MessageBridgeOutbox.query.count(),0)
        self.assertEqual(deliver_pending(),{"delivered":0,"failed":0,"disabled":True})
        self.assertEqual(self.rows(self.capture),[])
        self.app.config["MESSAGE_BRIDGE_ENABLED"] = True
        self.assertEqual(backfill_outbox(),1)
        self.assertEqual(deliver_pending()["delivered"],1)

    def test_backfill_exhausts_multiple_bounded_pages_before_nested_selects(self):
        self.app.config["MESSAGE_BRIDGE_ENABLED"] = False
        thread, first = self.new_thread("direct", [1, 2], commit=False)
        for index in range(422):
            db.session.add(InboxMessage(thread_id=int(thread.id),sender_id=2,content_md=f"Historical message {index}"))
        for index in range(217):
            db.session.add(Notification(user_id=1,type="historical_fixture",title=f"Historical notification {index}"))
        db.session.commit()
        message_ids={int(row[0]) for row in db.session.query(InboxMessage.id).all()}
        notification_ids={int(row[0]) for row in db.session.query(Notification.id).all()}
        self.assertEqual((len(message_ids),len(notification_ids)),(423,217))
        self.assertEqual(MessageBridgeOutbox.query.count(),0)
        self.app.config["MESSAGE_BRIDGE_ENABLED"] = True
        # SQLite cannot reproduce PyMySQL's abandoned SSCursor. Guard against
        # reintroducing streaming while testing all three source pages and the
        # enqueue helpers' real nested queries and autoflush behavior.
        with patch("sqlalchemy.orm.Query.yield_per",side_effect=AssertionError("historical results must be buffered")):
            self.assertEqual(backfill_outbox(),640)
            self.assertEqual(backfill_outbox(),0)
        rows=MessageBridgeOutbox.query.all()
        self.assertEqual({row.source_id for row in rows if row.event_kind=="inbox"},message_ids)
        self.assertEqual({row.source_id for row in rows if row.event_kind=="notification"},notification_ids)
        self.assertEqual(len({row.event_uid for row in rows}),640)
        self.assertEqual(self.rows(self.capture),[])
        self.assertEqual(self.rows(self.terminal),[])

    def test_after_request_delivers_only_committed_events(self):
        response = self.app.test_client().post("/emit")
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(self.rows(self.capture)),1)
        self.assertIsNotNone(MessageBridgeOutbox.query.first().delivered_at)

    def test_web_process_can_queue_without_accessing_private_capture_databases(self):
        self.app.config["MESSAGE_BRIDGE_INLINE_DELIVERY"]=False
        self.app.config["MESSAGE_BRIDGE_CAPTURE_DB"]=str(self.root/"private-unavailable.sqlite")
        response=self.app.test_client().post("/emit")
        self.assertEqual(response.status_code,200)
        self.assertEqual(MessageBridgeOutbox.query.count(),1)
        self.assertIsNone(MessageBridgeOutbox.query.first().delivered_at)
        self.assertEqual(self.rows(self.capture),[])
        self.assertEqual(self.rows(self.terminal),[])

    def test_departed_member_cannot_read_snapshot_and_other_private_user_is_denied(self):
        _,group = self.new_thread("project_group",[1,2])
        _,private = self.new_thread("direct",[1,2])
        group_uid,private_uid = event_uid("inbox",group.id),event_uid("inbox",private.id)
        self.assertTrue(can_read_netdisk_event(group_uid,2))
        db.session.delete(ProjectMember.query.filter_by(project_id=10,user_id=2).first())
        db.session.commit()
        self.assertFalse(can_read_netdisk_event(group_uid,2))
        self.assertFalse(can_read_netdisk_event(private_uid,3))
        self.assertTrue(can_read_netdisk_event(private_uid,1))

    def test_source_read_cursor_is_only_synced_for_configured_terminal_owner(self):
        thread,message = self.new_thread("direct",[1,2])
        deliver_pending()
        for user_id in (1,2):
            InboxRecipient.query.filter_by(thread_id=thread.id,user_id=user_id).first().last_read_at=utcnow()
        db.session.commit()
        self.assertEqual(sync_terminal_reads(2),0)
        self.assertEqual(self.rows(self.terminal,"SELECT is_read FROM messages WHERE source='netdisk'")[0]["is_read"],0)
        self.assertEqual(sync_terminal_reads(1),1)
        row=MessageBridgeOutbox.query.first()
        row.delivered_at=None
        db.session.commit()
        deliver_pending(retry_now=True)
        self.assertEqual(self.rows(self.terminal,"SELECT is_read FROM messages WHERE source='netdisk'")[0]["is_read"],1)

    def test_historical_backfill_is_read_and_quiet(self):
        self.app.config["MESSAGE_BRIDGE_ENABLED"]=False
        _,message=self.new_thread("direct",[1,2])
        message.created_at=utcnow()-dt.timedelta(days=2)
        db.session.commit()
        self.app.config["MESSAGE_BRIDGE_ENABLED"]=True
        backfill_outbox()
        deliver_pending()
        visible=self.rows(self.terminal,"SELECT * FROM messages WHERE source='netdisk'")[0]
        self.assertEqual((visible["is_read"],visible["notify"],visible["llm_status"]),(1,0,"skip"))


class EmptyIdentity:
    username=""
    names={}
    def __init__(self,*_args): pass
    def refresh(self,paths):
        if any(str(path).startswith("netdisk:") for path in paths):
            raise AssertionError("synthetic source must not enter WeChat identity resolver")
    def sender(self,_row): return ""
    def outgoing(self,_row): return False
    def details(self,_row): return {"sender_id":"","sender_name":"未知发送者","direction":"incoming"}


class QuietAttention:
    def __init__(self,_store): self.entries={}
    def route(self,*_args): return "ignore","一般消息","其它",False
    def mount(self,_api): pass
    def sync_directory(self): pass
    def display(self,_username,fallback=""): return fallback
    def tags(self,_entry): return ["其它"]


class InfoCenterBridgeTests(unittest.TestCase):
    new_thread=MessageBridgeTests.new_thread
    rows=MessageBridgeTests.rows
    tearDown=MessageBridgeTests.tearDown

    def setUp(self):
        MessageBridgeTests.setUp(self)
        self.server=Path(__file__).resolve().parents[1]/"integrations/DCP_InfoCenter/server"
        self.path_patch=patch.object(sys,"path",[str(self.server)]+sys.path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        attention=types.ModuleType("attention");attention.Attention=QuietAttention
        identity=types.ModuleType("sender_identity");identity.SenderIdentity=EmptyIdentity
        self.modules_patch=patch.dict(sys.modules,{"attention":attention,"sender_identity":identity})
        self.modules_patch.start()
        self.addCleanup(self.modules_patch.stop)
        spec=importlib.util.spec_from_file_location("netdisk_terminal_fixture",self.server/"terminal_backend.py")
        self.backend=importlib.util.module_from_spec(spec)
        with patch("zoneinfo.ZoneInfo",return_value=dt.timezone(dt.timedelta(hours=8))):
            spec.loader.exec_module(self.backend)
        (self.root/"config.json").write_text(json.dumps({"token":"fixture-token","llm":{"enabled":False}}),encoding="utf-8")
        self.store=self.backend.Store(self.root,wechat=self.capture)
        self.sidecar=Flask("sidecar-fixture")
        self.backend.mount(self.sidecar,store=self.store,start=False)
        self.client=self.sidecar.test_client()
        self.headers={"Authorization":"Bearer fixture-token"}

    def test_precise_unread_above_snapshot_limit_and_scoped_through_uid_reads(self):
        with self.store.connect() as terminal:
            for number in range(1105):
                terminal.execute("INSERT INTO messages(source,source_key,title,body,chat,occurred_at,created_at,payload) VALUES(?,?,?,?,?,?,?,?)",("wechat",f"real-{number}","微信会话","body","会话",number,number,json.dumps({"chat_id":"chat-a","message_uid":f"real-{number}"})))
            terminal.execute("INSERT INTO messages(source,source_key,title,body,chat,occurred_at,created_at,payload) VALUES(?,?,?,?,?,?,?,?)",("netdisk","netdisk:fixture:inbox:9000","网盘","body","网盘",5000,5000,json.dumps({"chat_id":"chat-b","message_uid":"netdisk:fixture:inbox:9000","sender_name":"member"})))
        response=self.client.get("/api/terminal/unread",headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json["unread_count"],1106)
        self.assertEqual(response.json["by_chat"],{"chat-a":1105,"chat-b":1})
        self.assertEqual(len(response.json["latest"]),20)
        pending=self.client.post("/api/terminal/conversations/read",json={"chat_id":"chat-a","through_uid":"not-yet-captured"},headers=self.headers)
        self.assertEqual(pending.status_code,202)
        self.assertTrue(pending.json["pending"])
        response=self.client.post("/api/terminal/conversations/read",json={"chat_id":"chat-a","through_uid":"real-1000"},headers=self.headers)
        self.assertEqual(response.json,{"pending":False,"changed":1001})
        response=self.client.get("/api/terminal/unread",headers=self.headers)
        self.assertEqual(response.json["unread_count"],105)
        self.assertEqual(response.json["by_chat"],{"chat-a":104,"chat-b":1})
        wrong=self.client.post("/api/terminal/conversations/read",json={"chat_id":"chat-b","through_uid":"real-1000"},headers=self.headers)
        self.assertEqual(wrong.status_code,202)
        self.assertEqual(self.client.get("/api/terminal/unread",headers=self.headers).json["unread_count"],105)

    def test_netdisk_collector_keeps_canonical_source_even_when_attention_ignores(self):
        _,message=self.new_thread("direct",[1,2])
        deliver_pending()
        with self.store.connect() as terminal:
            terminal.execute("DELETE FROM messages WHERE source='netdisk'")
        self.assertEqual(self.store.collect_wechat(),1)
        rows=self.rows(self.terminal,"SELECT * FROM messages WHERE is_outgoing=0")
        self.assertEqual([(row["source"],row["source_key"]) for row in rows],[("netdisk",event_uid("inbox",message.id))])
        payload=json.loads(rows[0]["payload"])
        self.assertEqual(payload["sender_name"],"member")
        self.assertEqual(payload["message_uid"],event_uid("inbox",message.id))
        self.assertEqual(rows[0]["llm_status"],"skip")

    def test_desktop_synthetic_sender_and_source_come_from_metadata(self):
        self.new_thread("direct",[1,2],content="raw markdown **hello**")
        deliver_pending()
        spec=importlib.util.spec_from_file_location("netdisk_desktop_fixture",self.server/"desktop_api.py")
        desktop=importlib.util.module_from_spec(spec);spec.loader.exec_module(desktop)
        store=desktop.DesktopStore(home=self.root,memory=self.capture,account=self.root/"account",identity=EmptyIdentity())
        with store.source() as capture:
            row=capture.execute("SELECT rowid,* FROM messages").fetchone()
        result=store.present(row)
        self.assertEqual(result["source"],"netdisk")
        self.assertEqual(result["sender"],"member")
        self.assertEqual(result["text"],"raw markdown **hello**")
        self.assertEqual(result["payload"]["message_uid"],result["uid"])
        self.assertFalse(result["outgoing"])

    def test_sidecar_shares_existing_stores_and_never_starts_workers(self):
        spec=importlib.util.spec_from_file_location("netdisk_sidecar_fixture",self.server/"sidecar.py")
        sidecar=importlib.util.module_from_spec(spec)
        with patch("zoneinfo.ZoneInfo",return_value=dt.timezone(dt.timedelta(hours=8))):
            spec.loader.exec_module(sidecar)
        with patch.dict("os.environ",{
            "DCP_TERMINAL_HOME":str(self.root),"DCP_CAPTURE_DB":str(self.capture),
            "DCP_WECHAT_ACCOUNT_DIR":str(self.root/"account"),
        }),patch.object(sidecar.Store,"start") as start:
            app=sidecar.create_app()
        start.assert_not_called()
        self.assertEqual(app.extensions["terminal"].db,self.terminal)
        self.assertEqual(app.extensions["desktop"].memory,self.capture)
        response=app.test_client().get("/api/terminal/unread",headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json["unread_count"],0)


if __name__=="__main__":
    unittest.main()
