import datetime as dt

from sqlalchemy import UniqueConstraint

from .extensions import db


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class User(db.Model, TimestampMixin):
    __tablename__ = "users"

    id = db.Column(db.BigInteger, primary_key=True)
    username = db.Column(db.String(64), nullable=False, unique=True)
    email = db.Column(db.String(255), nullable=True, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(64), nullable=False)
    avatar_file_id = db.Column(db.BigInteger, nullable=True)
    role_system = db.Column(db.String(32), nullable=False, default="user")
    status = db.Column(db.String(16), nullable=False, default="active")
    invite_code = db.Column(db.String(64), nullable=True, index=True)
    is_activated = db.Column(db.Boolean, nullable=False, default=False)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)


class UserSettings(db.Model, TimestampMixin):
    __tablename__ = "user_settings"

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.BigInteger, nullable=False, unique=True, index=True)
    theme_mode = db.Column(db.String(16), nullable=False, default="system")
    timezone = db.Column(db.String(64), nullable=False, default="Asia/Shanghai")
    locale = db.Column(db.String(32), nullable=False, default="zh-CN")
    notify_email = db.Column(db.Boolean, nullable=False, default=False)
    notify_in_app = db.Column(db.Boolean, nullable=False, default=True)


class AuthRefreshToken(db.Model, TimestampMixin):
    __tablename__ = "auth_refresh_tokens"

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.BigInteger, nullable=False, index=True)
    token_hash = db.Column(db.String(255), nullable=False, index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)


class InviteCode(db.Model, TimestampMixin):
    __tablename__ = "invite_codes"

    id = db.Column(db.BigInteger, primary_key=True)
    code = db.Column(db.String(64), nullable=False, unique=True, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    note = db.Column(db.String(255), nullable=True)
    created_by = db.Column(db.BigInteger, nullable=True, index=True)
    used_count = db.Column(db.BigInteger, nullable=False, default=0)
    max_uses = db.Column(db.BigInteger, nullable=True)


class Project(db.Model, TimestampMixin):
    __tablename__ = "projects"

    id = db.Column(db.BigInteger, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    key = db.Column(db.String(32), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=True)
    creator_id = db.Column(db.BigInteger, nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default="active")
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)


class ProjectMember(db.Model, TimestampMixin):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_user"),)

    id = db.Column(db.BigInteger, primary_key=True)
    project_id = db.Column(db.BigInteger, nullable=False, index=True)
    user_id = db.Column(db.BigInteger, nullable=False, index=True)
    role_project = db.Column(db.String(16), nullable=False, default="user")
    joined_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class ProjectSettings(db.Model, TimestampMixin):
    __tablename__ = "project_settings"

    id = db.Column(db.BigInteger, primary_key=True)
    project_id = db.Column(db.BigInteger, nullable=False, unique=True, index=True)
    guest_visible = db.Column(db.Boolean, nullable=False, default=False)
    task_workflow = db.Column(db.JSON, nullable=False)
    task_workflow_updated_at = db.Column(db.DateTime(timezone=True), nullable=True)


class Task(db.Model, TimestampMixin):
    __tablename__ = "tasks"

    id = db.Column(db.BigInteger, primary_key=True)
    project_id = db.Column(db.BigInteger, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    description_md = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(64), nullable=False)
    priority = db.Column(db.String(16), nullable=False, default="medium")
    assignee_id = db.Column(db.BigInteger, nullable=True, index=True)
    reporter_id = db.Column(db.BigInteger, nullable=False, index=True)
    start_at = db.Column(db.DateTime(timezone=True), nullable=True)
    due_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)


class TaskWatcher(db.Model, TimestampMixin):
    __tablename__ = "task_watchers"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_task_watcher"),)

    id = db.Column(db.BigInteger, primary_key=True)
    task_id = db.Column(db.BigInteger, nullable=False, index=True)
    user_id = db.Column(db.BigInteger, nullable=False, index=True)


class TaskComment(db.Model, TimestampMixin):
    __tablename__ = "task_comments"

    id = db.Column(db.BigInteger, primary_key=True)
    task_id = db.Column(db.BigInteger, nullable=False, index=True)
    user_id = db.Column(db.BigInteger, nullable=False, index=True)
    content_md = db.Column(db.Text, nullable=False)


class TaskAttachment(db.Model, TimestampMixin):
    __tablename__ = "task_attachments"
    __table_args__ = (UniqueConstraint("task_id", "file_id", name="uq_task_file"),)

    id = db.Column(db.BigInteger, primary_key=True)
    task_id = db.Column(db.BigInteger, nullable=False, index=True)
    file_id = db.Column(db.BigInteger, nullable=False, index=True)


class TaskActivityLog(db.Model):
    __tablename__ = "task_activity_logs"

    id = db.Column(db.BigInteger, primary_key=True)
    task_id = db.Column(db.BigInteger, nullable=False, index=True)
    actor_user_id = db.Column(db.BigInteger, nullable=False, index=True)
    action = db.Column(db.String(64), nullable=False)
    payload_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class StorageObject(db.Model, TimestampMixin):
    __tablename__ = "storage_objects"

    id = db.Column(db.BigInteger, primary_key=True)
    mime_type = db.Column(db.String(255), nullable=True)
    size_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    storage_rel_path = db.Column(db.String(512), nullable=False, unique=True)
    sha256 = db.Column(db.String(64), nullable=True, index=True)
    created_by = db.Column(db.BigInteger, nullable=False, index=True)


class FileNode(db.Model, TimestampMixin):
    __tablename__ = "file_nodes"

    id = db.Column(db.BigInteger, primary_key=True)
    type = db.Column(db.String(16), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    parent_id = db.Column(db.BigInteger, nullable=True, index=True)
    scope = db.Column(db.String(16), nullable=False)
    owner_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    project_id = db.Column(db.BigInteger, nullable=True, index=True)
    storage_object_id = db.Column(db.BigInteger, nullable=True, index=True)
    created_by = db.Column(db.BigInteger, nullable=False, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)


class CalendarEvent(db.Model, TimestampMixin):
    __tablename__ = "calendar_events"
    __table_args__ = (db.UniqueConstraint("created_by", "client_request_id", name="uq_calendar_request"),)

    id = db.Column(db.BigInteger, primary_key=True)
    scope = db.Column(db.String(16), nullable=False)
    owner_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    project_id = db.Column(db.BigInteger, nullable=True, index=True)
    assignee_id = db.Column(db.BigInteger, nullable=True, index=True)
    title = db.Column(db.String(255), nullable=False)
    description_md = db.Column(db.Text, nullable=True)
    start_at = db.Column(db.DateTime(timezone=True), nullable=False)
    end_at = db.Column(db.DateTime(timezone=True), nullable=False)
    all_day = db.Column(db.Boolean, nullable=False, default=False)
    location = db.Column(db.String(255), nullable=True)
    created_by = db.Column(db.BigInteger, nullable=False, index=True)
    client_request_id = db.Column(db.String(80), nullable=True)
    request_digest = db.Column(db.String(64), nullable=True)


class ScheduleOverride(db.Model, TimestampMixin):
    """An account's forced completion, including immutable external calendars."""
    __tablename__ = "schedule_overrides"
    __table_args__ = (db.UniqueConstraint("user_id", "schedule_uid", name="uq_schedule_override_user_uid"),)

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.BigInteger, nullable=False, index=True)
    schedule_uid = db.Column(db.String(512), nullable=False)
    forced_completed = db.Column(db.Boolean, nullable=False, default=False)


class InboxThread(db.Model, TimestampMixin):
    __tablename__ = "inbox_threads"

    id = db.Column(db.BigInteger, primary_key=True)
    type = db.Column(db.String(16), nullable=False)
    subject = db.Column(db.String(255), nullable=True)
    created_by = db.Column(db.BigInteger, nullable=False, index=True)


class InboxMessage(db.Model, TimestampMixin):
    __tablename__ = "inbox_messages"

    id = db.Column(db.BigInteger, primary_key=True)
    thread_id = db.Column(db.BigInteger, nullable=False, index=True)
    sender_id = db.Column(db.BigInteger, nullable=False, index=True)
    content_md = db.Column(db.Text, nullable=False)


class InboxRecipient(db.Model, TimestampMixin):
    __tablename__ = "inbox_recipients"
    __table_args__ = (UniqueConstraint("thread_id", "user_id", name="uq_thread_user"),)

    id = db.Column(db.BigInteger, primary_key=True)
    thread_id = db.Column(db.BigInteger, nullable=False, index=True)
    user_id = db.Column(db.BigInteger, nullable=False, index=True)
    last_read_at = db.Column(db.DateTime(timezone=True), nullable=True)


class Notification(db.Model, TimestampMixin):
    __tablename__ = "notifications"

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.BigInteger, nullable=False, index=True)
    type = db.Column(db.String(64), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=True)
    link_url = db.Column(db.String(512), nullable=True)
    meta_json = db.Column(db.JSON, nullable=True)
    read_at = db.Column(db.DateTime(timezone=True), nullable=True)


class MessageBridgeOutbox(db.Model):
    """Committed messages awaiting idempotent publication to the capture store."""

    __tablename__ = "message_bridge_outbox"

    id = db.Column(db.BigInteger, primary_key=True)
    event_uid = db.Column(db.String(191), nullable=False, unique=True)
    event_kind = db.Column(db.String(32), nullable=False)
    source_id = db.Column(db.BigInteger, nullable=False, index=True)
    payload_json = db.Column(db.JSON, nullable=False)
    reply_request_key = db.Column(db.String(64), nullable=True, unique=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.String(64), nullable=True)
    next_attempt_at = db.Column(db.DateTime(timezone=True), nullable=True)
    delivered_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
