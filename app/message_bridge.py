"""Publish committed NetDisk events to the local capture and Terminal stores.

This module only mirrors database records. It does not import a WeChat sender,
contact the network, or send messages to real WeChat accounts.
"""

import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

import click
from flask import current_app, has_app_context
from sqlalchemy import event, or_
from sqlalchemy.orm import Session

from .extensions import db
from .models import (
    InboxMessage, InboxRecipient, InboxThread, MessageBridgeOutbox, Notification,
    Project, ProjectMember, Task, TaskComment, User, utcnow,
)


SOURCE = "netdisk"
META_TABLE = "netdisk_message_meta"
_PENDING = "netdisk_bridge_pending"
_QUEUED = "netdisk_bridge_queued"
_COMMITTED = "netdisk_bridge_committed"


def enabled():
    return has_app_context() and bool(current_app.config.get("MESSAGE_BRIDGE_ENABLED", False))


def instance_id():
    value = str(current_app.config.get("MESSAGE_BRIDGE_INSTANCE_ID") or "dcp-netdisk")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("MESSAGE_BRIDGE_INSTANCE_ID is invalid")
    return value


def as_utc(value):
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)


def event_uid(kind, source_id):
    return f"{SOURCE}:{instance_id()}:{kind}:{int(source_id)}"


def _sender(user_id, system=False):
    user = db.session.get(User, int(user_id)) if user_id else None
    if system or not user:
        return "Server", ""
    return user.display_name or user.username, user.username


def _enqueue(kind, source_id, payload):
    uid = event_uid(kind, source_id)
    # During after_flush_postexec a canonical notification may enrich the
    # Inbox event queued earlier in this same flush. Its outbox row has not
    # reached the database yet, so check the unit of work before querying.
    existing = next((row for row in db.session.new
                     if isinstance(row, MessageBridgeOutbox) and row.event_uid == uid), None)
    if existing is None:
        existing = MessageBridgeOutbox.query.filter_by(event_uid=uid).first()
    if existing:
        if existing.delivered_at is None:
            existing.payload_json = dict(existing.payload_json, **payload)
        return existing
    payload.update(message_uid=uid, source=SOURCE, instance_id=instance_id(), event_kind=kind, source_id=int(source_id))
    row = MessageBridgeOutbox(event_uid=uid, event_kind=kind, source_id=int(source_id), payload_json=payload)
    db.session.add(row)
    db.session.info[_QUEUED] = True
    return row


def enqueue_inbox_message(message):
    """Queue within the caller's transaction; never commit or publish here."""
    if not enabled() or message.id is None:
        return None
    thread = db.session.get(InboxThread, int(message.thread_id))
    if not thread:
        return None
    project_id = None
    if thread.type == "project_group" and (thread.subject or "").startswith("project:"):
        project_id = int(thread.subject.split(":", 1)[1])
    recipients = {int(row.user_id) for row in InboxRecipient.query.filter_by(thread_id=int(thread.id)).all()}
    if project_id:
        project = db.session.get(Project, project_id)
        if project:
            recipients.add(int(project.creator_id))
        recipients.update(int(row.user_id) for row in ProjectMember.query.filter_by(project_id=project_id).all())
        chat_id = f"{SOURCE}:{instance_id()}:project:{project_id}@chatroom"
        chat_name = f"项目:{project.name if project else project_id}"
    else:
        chat_id = f"{SOURCE}:{instance_id()}:thread:{int(thread.id)}"
        chat_name = thread.subject or ("系统消息" if thread.type == "system" else "网盘私聊")
    sender_name, sender_username = _sender(message.sender_id, system=thread.type == "system" or not message.sender_id)
    related = None
    if thread.type == "system" and recipients:
        related = Notification.query.filter(
            Notification.user_id.in_(recipients), Notification.type == "system",
            Notification.title == thread.subject, Notification.content == message.content_md,
        ).order_by(Notification.id.desc()).first()
    return _enqueue("inbox", message.id, {
        "thread_id": int(thread.id), "thread_type": thread.type,
        "project_id": project_id, "sender_user_id": int(message.sender_id or 0),
        "sender_name": sender_name, "sender_username": sender_username,
        "recipient_ids": sorted(recipients), "chat_id": chat_id, "chat_name": chat_name,
        "content": message.content_md or "", "title": chat_name,
        "link_url": related.link_url if related else None,
        "user_id": (related.meta_json or {}).get("user_id") if related else None,
        "occurred_at": int(as_utc(message.created_at or utcnow()).timestamp()),
    })


def _has_canonical_inbox(notification):
    if notification.type in ("inbox_message", "mention"):
        metadata = notification.meta_json or {}
        if not isinstance(metadata, dict) or not metadata.get("thread_id"):
            return False
        try:
            thread_id = int(metadata["thread_id"])
            message_id = int(metadata["message_id"]) if metadata.get("message_id") else None
        except (TypeError, ValueError):
            return False
        canonical = db.session.query(InboxMessage.id).join(
            InboxThread, InboxThread.id == InboxMessage.thread_id,
        ).filter(InboxThread.id == thread_id)
        if message_id:
            canonical = canonical.filter(InboxMessage.id == message_id)
        else:
            stamp = as_utc(notification.created_at or utcnow())
            canonical = canonical.filter(
                InboxMessage.created_at >= stamp - dt.timedelta(seconds=2),
                InboxMessage.created_at <= stamp + dt.timedelta(seconds=2),
            )
        match = canonical.order_by(InboxMessage.id.desc()).first()
        return int(match[0]) if match else False
    if notification.type != "system" or not notification.content:
        return False
    stamp = as_utc(notification.created_at or utcnow())
    canonical = db.session.query(InboxMessage.id).join(
        InboxThread, InboxThread.id == InboxMessage.thread_id,
    ).join(InboxRecipient, InboxRecipient.thread_id == InboxThread.id).filter(
        InboxThread.type == "system", InboxThread.subject == notification.title,
        InboxRecipient.user_id == int(notification.user_id),
        InboxMessage.content_md == notification.content,
        InboxMessage.created_at >= stamp - dt.timedelta(seconds=2),
        InboxMessage.created_at <= stamp + dt.timedelta(seconds=2),
    ).first()
    return int(canonical[0]) if canonical else False


def enqueue_task_comment(comment):
    """Mirror full task discussion into its project chat in the same transaction."""
    if not enabled() or comment.id is None:
        return None
    task = db.session.get(Task, int(comment.task_id))
    project = db.session.get(Project, int(task.project_id)) if task else None
    if not task or not project:
        return None
    thread = InboxThread.query.filter_by(
        type="project_group", subject=f"project:{int(project.id)}",
    ).order_by(InboxThread.id).first()
    recipients = {int(project.creator_id)}
    recipients.update(int(row.user_id) for row in ProjectMember.query.filter_by(project_id=int(project.id)).all())
    sender_name, sender_username = _sender(comment.user_id)
    chat_name = f"项目:{project.name}"
    return _enqueue("task_comment", comment.id, {
        "thread_id": int(thread.id) if thread else None, "thread_type": "project_group",
        "project_id": int(project.id), "task_id": int(task.id), "comment_id": int(comment.id),
        "task_title": task.title, "sender_user_id": int(comment.user_id),
        "sender_name": sender_name, "sender_username": sender_username,
        "recipient_ids": sorted(recipients),
        "chat_id": f"{SOURCE}:{instance_id()}:project:{int(project.id)}@chatroom",
        "chat_name": chat_name, "title": f"任务评论:{task.title}",
        "content": comment.content_md or "",
        "link_url": f"/projects/{int(project.id)}?tab=tasks&task={int(task.id)}",
        "occurred_at": int(as_utc(comment.created_at or utcnow()).timestamp()),
    })


def enqueue_notification(notification):
    if not enabled() or notification.id is None:
        return None
    canonical = _has_canonical_inbox(notification)
    if canonical:
        if type(canonical) is int:
            enqueue_inbox_message(db.session.get(InboxMessage, canonical))
        return None
    return _enqueue("notification", notification.id, {
        "thread_id": None, "thread_type": "system", "project_id": None,
        "sender_user_id": 0, "sender_name": "Server", "sender_username": "",
        "recipient_ids": [int(notification.user_id)],
        "chat_id": f"{SOURCE}:{instance_id()}:system:user:{int(notification.user_id)}",
        "chat_name": "Server · 系统通知", "title": notification.title,
        "content": notification.title + ("\n" + notification.content if notification.content else ""),
        "link_url": notification.link_url, "notification_type": notification.type,
        "user_id": (notification.meta_json or {}).get("user_id"),
        "occurred_at": int(as_utc(notification.created_at or utcnow()).timestamp()),
    })


def can_read_netdisk_event(uid, user_id):
    """Use current source permissions, never stale exported recipient snapshots."""
    row = MessageBridgeOutbox.query.filter_by(event_uid=str(uid)).first()
    user = db.session.get(User, int(user_id))
    if not row or not user or user.status != "active" or not user.is_activated:
        return False
    if user.role_system == "super_admin":
        return True
    payload = row.payload_json
    if payload.get("project_id"):
        project = db.session.get(Project, int(payload["project_id"]))
        return bool(project and (int(project.creator_id) == int(user_id) or ProjectMember.query.filter_by(
            project_id=int(project.id), user_id=int(user_id),
        ).first()))
    if payload.get("thread_id"):
        return InboxRecipient.query.filter_by(thread_id=int(payload["thread_id"]), user_id=int(user_id)).first() is not None
    notification = db.session.get(Notification, int(row.source_id)) if row.event_kind == "notification" else None
    return bool(notification and int(notification.user_id) == int(user_id))


def sync_terminal_reads(user_id=None):
    """Mirror the configured Terminal owner's Inbox read cursor, not other users'."""
    owner = current_app.config.get("MESSAGE_BRIDGE_TERMINAL_USER_ID")
    path = current_app.config.get("MESSAGE_BRIDGE_TERMINAL_DB")
    if not enabled() or not owner or not path or (user_id is not None and int(user_id) != int(owner)):
        return 0
    cursors = InboxRecipient.query.filter_by(user_id=int(owner)).filter(InboxRecipient.last_read_at.isnot(None)).all()
    changed = 0
    with _existing_sqlite(path) as terminal:
        for cursor in cursors:
            uid_rows = db.session.query(MessageBridgeOutbox.event_uid).join(
                InboxMessage, InboxMessage.id == MessageBridgeOutbox.source_id,
            ).filter(
                MessageBridgeOutbox.event_kind == "inbox", InboxMessage.thread_id == int(cursor.thread_id),
                InboxMessage.created_at <= cursor.last_read_at,
            ).all()
            for (uid,) in uid_rows:
                changed += terminal.execute("UPDATE messages SET is_read=1 WHERE source=? AND source_key=? AND is_read=0", (SOURCE, uid)).rowcount
    return changed


def _capture_new_events(session, _flush_context, _instances):
    if enabled() and current_app.extensions.get("message_bridge"):
        pending = session.info.setdefault(_PENDING, [])
        pending.extend(row for row in session.new if isinstance(row, (InboxMessage, TaskComment, Notification)))


def _queue_flushed_events(session, _flush_context):
    pending = session.info.pop(_PENDING, [])
    if not pending or not enabled():
        return
    for row in pending:
        if isinstance(row, InboxMessage):
            enqueue_inbox_message(row)
    for row in pending:
        if isinstance(row, TaskComment):
            enqueue_task_comment(row)
    for row in pending:
        if isinstance(row, Notification):
            enqueue_notification(row)


def _source_committed(session):
    if session.info.pop(_QUEUED, False):
        session.info[_COMMITTED] = True


def _source_rolled_back(session):
    for key in (_PENDING, _QUEUED, _COMMITTED):
        session.info.pop(key, None)


event.listen(Session, "before_flush", _capture_new_events)
event.listen(Session, "after_flush_postexec", _queue_flushed_events)
event.listen(Session, "after_commit", _source_committed)
event.listen(Session, "after_rollback", _source_rolled_back)


@contextlib.contextmanager
def _existing_sqlite(path):
    # mode=rw requires an existing DB and prevents a typo creating an empty store.
    target = Path(os.path.expanduser(str(path))).resolve()
    connection = sqlite3.connect(target.as_uri() + "?mode=rw", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _columns(connection, table):
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def _insert_known(connection, table, values):
    values = {key: value for key, value in values.items() if key in _columns(connection, table)}
    columns = ",".join(values)
    placeholders = ",".join("?" for _ in values)
    connection.execute(f"INSERT OR IGNORE INTO {table} ({columns}) VALUES ({placeholders})", list(values.values()))


def publish_capture(payload, path):
    uid = payload["message_uid"]
    rendered = f"[NetDisk · {payload['sender_name']}]\n{payload['content']}"
    stamp = int(payload["occurred_at"])
    now = utcnow().isoformat()
    with _existing_sqlite(path) as capture:
        required = {"message_uid", "chat_username", "message_content", "create_time"}
        if not required <= _columns(capture, "messages"):
            raise ValueError("capture messages schema is incompatible")
        capture.execute(f"""CREATE TABLE IF NOT EXISTS {META_TABLE} (
            message_uid TEXT PRIMARY KEY, source TEXT NOT NULL,
            instance_id TEXT NOT NULL, event_kind TEXT NOT NULL, source_id INTEGER NOT NULL,
            thread_id INTEGER, thread_type TEXT NOT NULL, project_id INTEGER,
            sender_user_id INTEGER NOT NULL, sender_name TEXT NOT NULL,
            recipient_ids TEXT NOT NULL, payload_json TEXT NOT NULL
        )""")
        _insert_known(capture, "messages", {
            "message_uid": uid, "chat_username": payload["chat_id"],
            "chat_display_name": payload["chat_name"], "message_table": "netdisk_" + payload["event_kind"],
            "source_message_db": "", "local_id": int(payload["source_id"]),
            "server_id": None, "local_type": 1, "base_type": 1, "app_subtype": 0,
            "type_label": "NetDisk", "sort_seq": stamp * 1000,
            "real_sender_id": 0, "create_time": stamp, "status": 0,
            "upload_status": 0, "download_status": 0, "server_seq": 0,
            "origin_source": 0, "source": SOURCE, "message_content": rendered,
            "compress_content": None, "content_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
            "packed_info_sha256": None, "ingested_at": now,
        })
        if not capture.execute("SELECT 1 FROM messages WHERE message_uid=?", (uid,)).fetchone():
            raise ValueError("capture event was not inserted")
        capture.execute(f"INSERT OR IGNORE INTO {META_TABLE} VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
            uid, SOURCE, payload["instance_id"], payload["event_kind"], payload["source_id"],
            payload.get("thread_id"), payload["thread_type"], payload.get("project_id"),
            payload["sender_user_id"], payload["sender_name"],
            json.dumps(payload["recipient_ids"]), json.dumps(payload, ensure_ascii=False),
        ))
        if _columns(capture, "chats"):
            capture.execute("""INSERT INTO chats
                (username,display_name,is_group,last_timestamp,sort_timestamp,message_table,source_message_db,updated_at)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(username) DO UPDATE SET
                display_name=excluded.display_name,is_group=excluded.is_group,
                last_timestamp=MAX(COALESCE(chats.last_timestamp,0),excluded.last_timestamp),
                sort_timestamp=MAX(COALESCE(chats.sort_timestamp,0),excluded.sort_timestamp),
                updated_at=excluded.updated_at""", (
                payload["chat_id"], payload["chat_name"], int(payload["thread_type"] == "project_group"),
                stamp, stamp, "netdisk_" + payload["event_kind"], "", now,
            ))


def publish_terminal(payload, path, reserve_legacy=True):
    """Preserve Terminal's canonical read state and source-key deduplication."""
    now = int(utcnow().timestamp() * 1000)
    fresh = now - int(payload["occurred_at"]) * 1000 < 24 * 3600 * 1000
    encoded = json.dumps(dict(payload, direction="incoming", message_kind="网盘消息", category="NetDisk"), ensure_ascii=False)
    with _existing_sqlite(path) as terminal:
        required = {"source", "source_key", "title", "body", "payload", "is_outgoing"}
        if not required <= _columns(terminal, "messages"):
            raise ValueError("terminal messages schema is incompatible")
        base = {
            "source": SOURCE, "source_key": payload["message_uid"],
            "title": payload.get("title") or payload["chat_name"], "body": payload["content"],
            "chat": payload["chat_name"], "occurred_at": int(payload["occurred_at"]) * 1000,
            "created_at": now, "is_read": int(not fresh), "notify": int(fresh),
            "payload": encoded, "llm_status": "skip", "llm_attempts": 0,
            "llm_retry_at": 0, "is_outgoing": 0,
        }
        _insert_known(terminal, "messages", base)
        if reserve_legacy:
            # Existing unmodified collectors still scan every capture row as
            # WeChat. Reserve this UID as an invisible compatibility alias.
            alias = dict(base, source="wechat", is_outgoing=1, notify=0, is_read=1)
            _insert_known(terminal, "messages", alias)
            terminal.execute("""UPDATE messages SET is_outgoing=1,notify=0,is_read=1,llm_status='skip'
                WHERE source='wechat' AND source_key=?""", (payload["message_uid"],))


def deliver_pending(limit=100, retry_now=False):
    if not enabled():
        return {"delivered": 0, "failed": 0, "disabled": True}
    capture_path = current_app.config.get("MESSAGE_BRIDGE_CAPTURE_DB")
    terminal_path = current_app.config.get("MESSAGE_BRIDGE_TERMINAL_DB")
    if not capture_path:
        return {"delivered": 0, "failed": 0, "unconfigured": True}
    query = MessageBridgeOutbox.query.filter(MessageBridgeOutbox.delivered_at.is_(None))
    if not retry_now:
        query = query.filter(or_(MessageBridgeOutbox.next_attempt_at.is_(None), MessageBridgeOutbox.next_attempt_at <= utcnow()))
    rows = query.order_by(MessageBridgeOutbox.id).with_for_update(skip_locked=True).limit(max(1, min(int(limit), 10000))).all()
    result = {"delivered": 0, "failed": 0}
    for row in rows:
        row.attempts = int(row.attempts or 0) + 1
        try:
            # Commit the Terminal reservation first so the legacy collector
            # cannot race a visible duplicate after capture publication.
            if terminal_path:
                publish_terminal(row.payload_json, terminal_path, current_app.config.get("MESSAGE_BRIDGE_RESERVE_LEGACY", True))
            publish_capture(row.payload_json, capture_path)
            row.delivered_at = utcnow()
            row.last_error = None
            row.next_attempt_at = None
            result["delivered"] += 1
        except (OSError, ValueError, sqlite3.Error) as exc:
            row.last_error = type(exc).__name__
            row.next_attempt_at = utcnow() + dt.timedelta(seconds=min(3600, 30 * 2 ** min(row.attempts, 7)))
            result["failed"] += 1
            current_app.logger.warning("Message bridge publication failed: %s", type(exc).__name__)
    db.session.commit()
    if terminal_path:
        try:
            sync_terminal_reads()
        except (OSError, ValueError, sqlite3.Error) as exc:
            current_app.logger.warning("Message bridge read sync deferred: %s", type(exc).__name__)
    return result


def backfill_outbox():
    if not enabled():
        return 0
    before = MessageBridgeOutbox.query.count()
    # Enqueue performs related SELECTs and flushes. Exhaust each bounded
    # result before those operations so MySQL's unbuffered cursor cannot be
    # replaced while the historical source result is still being consumed.
    for model, enqueue in ((InboxMessage, enqueue_inbox_message), (TaskComment, enqueue_task_comment), (Notification, enqueue_notification)):
        cursor = 0
        while True:
            rows = model.query.filter(model.id > cursor).order_by(model.id).limit(200).all()
            if not rows:
                break
            cursor = int(rows[-1].id)
            for row in rows:
                enqueue(row)
    db.session.commit()
    return MessageBridgeOutbox.query.count() - before


def register_message_bridge(app):
    if app.extensions.get("message_bridge"):
        return
    app.extensions["message_bridge"] = True

    @app.after_request
    def publish_committed_events(response):
        committed = db.session.info.pop(_COMMITTED, False)
        if enabled() and app.config.get("MESSAGE_BRIDGE_INLINE_DELIVERY", False) and committed:
            try:
                deliver_pending(limit=int(app.config.get("MESSAGE_BRIDGE_REQUEST_LIMIT", 20)))
            except Exception as exc:
                db.session.rollback()
                app.logger.warning("Message bridge retry deferred: %s", type(exc).__name__)
        return response

    @app.cli.command("message-bridge")
    @click.option("--backfill", is_flag=True, help="Queue canonical historical NetDisk messages and notifications.")
    @click.option("--dry-run", is_flag=True, help="Count pending events without writing either external database.")
    @click.option("--retry-now", is_flag=True, help="Ignore publication retry delays.")
    @click.option("--limit", default=1000, type=click.IntRange(1, 10000))
    def message_bridge_command(backfill, dry_run, retry_now, limit):
        if dry_run:
            click.echo(json.dumps({"pending": MessageBridgeOutbox.query.filter_by(delivered_at=None).count(), "enabled": enabled()}))
            return
        queued = backfill_outbox() if backfill else 0
        result = dict(deliver_pending(limit, retry_now), queued=queued)
        click.echo(json.dumps(result))
        if result.get("failed") or result.get("unconfigured"):
            raise click.ClickException("Some message publications remain pending.")
