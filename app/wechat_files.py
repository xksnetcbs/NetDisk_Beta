"""Copy available WeChat attachments into a private, readable NetDisk project.

The capture database and WeChat files are strictly read-only. There is no CDN,
GUI, or sender integration. A message UID is the stable source identity; an
unavailable source never deletes an existing NetDisk copy.
"""

import contextlib
import datetime as dt
import hashlib
import html
import itertools
import json
import mimetypes
import os
from pathlib import Path
import re
import sqlite3
import xml.etree.ElementTree as ET

import click
from flask import current_app
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from .extensions import db
from .models import FileNode, Project, ProjectMember, ProjectSettings, StorageObject, User, utcnow
from .readable_storage import safe_name
from .services import default_workflow
from .storage import new_object_path, resolve_object_path


class WeChatFileSyncState(db.Model):
    __tablename__ = "wechat_file_sync_states"

    instance_id = db.Column(db.String(64), primary_key=True)
    project_id = db.Column(db.BigInteger, nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    last_scan_at = db.Column(db.DateTime(timezone=True), nullable=True)


class WeChatFileImport(db.Model):
    __tablename__ = "wechat_file_imports"
    __table_args__ = (db.UniqueConstraint("instance_id", "source_uid", name="uq_wechat_file_source"),)

    id = db.Column(db.BigInteger, primary_key=True)
    instance_id = db.Column(db.String(64), nullable=False, index=True)
    source_uid = db.Column(db.String(64), nullable=False)
    message_uid = db.Column(db.Text, nullable=False)
    chat_username = db.Column(db.Text, nullable=False)
    source_kind = db.Column(db.String(16), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    source_rel_path = db.Column(db.Text, nullable=True)
    source_signature = db.Column(db.String(191), nullable=True)
    source_md5 = db.Column(db.String(32), nullable=True)
    source_sha256 = db.Column(db.String(64), nullable=True)
    size_bytes = db.Column(db.BigInteger, nullable=True)
    file_node_id = db.Column(db.BigInteger, nullable=True, index=True)
    status = db.Column(db.String(32), nullable=False, default="pending")
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    synced_at = db.Column(db.DateTime(timezone=True), nullable=True)


MEDIA_TYPES = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
    "image/webp": ".webp", "audio/mpeg": ".mp3", "audio/wav": ".wav",
    "audio/ogg": ".ogg", "video/mp4": ".mp4",
}


def instance_id():
    value = str(current_app.config.get("WECHAT_FILES_INSTANCE_ID") or "linux-wechat")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("invalid WeChat files instance")
    return value


def source_uid(message_uid):
    return hashlib.sha256(str(message_uid).encode("utf-8")).hexdigest()


def parse_attachment(body):
    body = re.sub(r"^[\w@.-]+:\r?\n", "", str(body or ""), count=1).strip()
    if body.startswith("&lt;"):
        body = html.unescape(body)
    if len(body) > 1024 * 1024 or "<!DOCTYPE" in body.upper() or "<!ENTITY" in body.upper():
        return None
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    app = root if root.tag == "appmsg" else root.find(".//appmsg")
    if app is None or app.findtext("type", "") != "6":
        return None
    size = app.findtext("appattach/totallen", "")
    md5 = (app.findtext("md5", "") or app.findtext("appattach/md5", "")).lower().strip()
    if not size.isdigit() or (md5 and not re.fullmatch(r"[0-9a-f]{32}", md5)):
        return None
    name = app.findtext("title", "") or "未命名文件"
    return {"name": name, "size": int(size), "md5": md5}


def _inside_file(path, root):
    """Reject traversal and every symlink component, including parent symlinks."""
    path, root = Path(path), Path(root)
    try:
        path = path.absolute()
        relative = path.relative_to(root)
        cursor = root
        for part in relative.parts:
            cursor /= part
            if cursor.is_symlink():
                return None
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            return None
        return resolved
    except (OSError, ValueError):
        return None


def _signature(stat):
    return ":".join(str(value) for value in (
        stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino,
    ))


def _read_hash(path, expected_size=None, expected_md5="", destination=None):
    sha, md5 = hashlib.sha256(), hashlib.md5()
    # Do not hard-link a WeChat source into managed storage: later writes to the
    # WeChat download must never mutate an already imported NetDisk object.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(fd, "rb", closefd=False) as source:
            before = os.fstat(fd)
            with (open(destination, "xb") if destination else contextlib.nullcontext()) as output:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    sha.update(chunk)
                    md5.update(chunk)
                    if output:
                        output.write(chunk)
                if output:
                    output.flush()
                    os.fsync(output.fileno())
            after = os.fstat(fd)
        if _signature(before) != _signature(after) or _signature(after) != _signature(Path(path).stat()):
            raise ValueError("source_changed")
        if expected_size is not None and after.st_size != expected_size:
            raise ValueError("size_mismatch")
        if expected_md5 and md5.hexdigest() != expected_md5:
            raise ValueError("hash_mismatch")
        return sha.hexdigest(), _signature(after), after.st_size
    finally:
        os.close(fd)


class CaptureFiles:
    """A bounded source reader; never writes SQLite schema or source bytes."""

    def __init__(self):
        configured = current_app.config.get("WECHAT_FILES_CAPTURE_DB") or current_app.config.get("MESSAGE_BRIDGE_CAPTURE_DB")
        if not configured:
            raise ValueError("WeChat capture database is not configured")
        self.memory = Path(os.path.expanduser(str(configured))).absolute()
        root = current_app.config.get("WECHAT_FILES_SOURCE_ROOT")
        if not root:
            # This reads only the account directory from the existing private
            # collector configuration. None of its other values are retained.
            config = self.memory.parent.parent / "wechat-decrypt" / "config.json"
            root = Path(json.loads(config.read_text(encoding="utf-8"))["db_dir"]).parent / "msg" / "file"
        self.file_root = Path(os.path.expanduser(str(root))).resolve(strict=True)
        if not self.file_root.is_dir():
            raise ValueError("WeChat attachment directory is unavailable")
        media = current_app.config.get("WECHAT_FILES_MEDIA_ROOT") or self.memory.parent.parent / "media"
        self.media_root = Path(os.path.expanduser(str(media))).resolve()
        self.files_by_size = {}
        for directory, subdirs, filenames in os.walk(self.file_root, followlinks=False):
            subdirs[:] = [name for name in subdirs if not (Path(directory) / name).is_symlink()]
            for name in sorted(filenames):
                path = _inside_file(Path(directory) / name, self.file_root)
                if path is not None:
                    try:
                        self.files_by_size.setdefault(path.stat().st_size, []).append(path)
                    except OSError:
                        pass
        self.digest_cache = {}
        self.matched_files = set()

    @contextlib.contextmanager
    def source(self):
        with contextlib.closing(sqlite3.connect(self.memory.as_uri() + "?mode=ro", uri=True, timeout=15)) as connection:
            connection.row_factory = sqlite3.Row
            yield connection

    def messages(self):
        with self.source() as connection:
            has_media = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='message_media'").fetchone()
            media_columns = {row["name"] for row in connection.execute("PRAGMA table_info(message_media)")} if has_media else set()
            fields = ", mm.media_path AS indexed_media_path, mm.mime_type AS indexed_mime_type, mm.status AS indexed_status" if has_media else ""
            join = " LEFT JOIN message_media mm ON mm.message_uid=m.message_uid" if has_media else ""
            # A decoded, indexed media file is authoritative even when the
            # capture uses an unfamiliar message type. Known unready media
            # still retain their retry state; no unindexed runtime scan occurs.
            kinds = "(m.base_type=49 OR (m.base_type IN (3,34,43,47) AND mm.message_uid IS NOT NULL) OR mm.status='ready')" if has_media else "m.base_type=49"
            media_filter = " AND COALESCE(mm.chat_username,'') NOT LIKE 'netdisk:%'" if "chat_username" in media_columns else ""
            query = (
                "SELECT m.message_uid,m.chat_username,m.chat_display_name,m.create_time,m.base_type,m.message_content" + fields + " FROM messages m" + join
                + " WHERE " + kinds
                + " AND COALESCE(m.source_message_db,'') != ''"
                + " AND COALESCE(m.chat_username,'') NOT LIKE 'netdisk:%'"
                + " AND m.message_uid NOT LIKE 'netdisk:%'" + media_filter + " ORDER BY m.create_time,m.message_uid"
            )
            # End the capture read transaction before copying files or writing
            # NetDisk records, including installations without SQLite WAL.
            rows = [dict(row) for row in connection.execute(query).fetchall()]
            orphan_media = []
            if has_media:
                chat = "mm.chat_username" if "chat_username" in media_columns else "''"
                orphan_media = [dict(row) for row in connection.execute(
                    "SELECT mm.message_uid,mm.media_path,mm.mime_type," + chat + " AS media_chat FROM message_media mm"
                    " LEFT JOIN messages m ON m.message_uid=mm.message_uid WHERE mm.status='ready'"
                    " AND (m.message_uid IS NULL OR COALESCE(m.source_message_db,'')='')"
                    " AND mm.message_uid NOT LIKE 'netdisk:%' AND COALESCE(m.chat_username,'') NOT LIKE 'netdisk:%'"
                ).fetchall()]
        for row in rows:
            item = dict(row)
            try:
                base_type = int(item["base_type"])
            except (ValueError, TypeError):
                base_type = 0
            metadata = parse_attachment(item["message_content"]) if base_type == 49 else None
            if base_type == 49 and not metadata and item.get("indexed_status") != "ready":
                continue
            item["attachment"] = metadata
            if metadata is None:
                if base_type not in (3, 34, 43, 47):
                    mime = item.get("indexed_mime_type") or ""
                    base_type = 34 if mime.startswith("audio/") else 43 if mime.startswith("video/") else 3
            if not item["chat_username"] or not item["chat_username"].strip():
                item.update(chat_username="__unlinked_capture__", chat_display_name="未关联会话", unlinked_chat=True)
                if metadata is None:
                    item["orphan_media"] = True
            item["base_type"] = base_type
            yield item
        for row in orphan_media:
            if str(row["media_chat"] or "").startswith("netdisk:") or row["mime_type"] not in MEDIA_TYPES:
                continue
            value = Path(row["media_path"] or "")
            if not value.is_absolute():
                value = self.media_root.parent / value
            path = _inside_file(value, self.media_root)
            stamp = int(path.stat().st_mtime) if path else 0
            yield {
                "message_uid": row["message_uid"], "chat_username": "__unlinked_media__",
                "chat_display_name": "未关联会话", "create_time": stamp,
                "base_type": 34 if row["mime_type"].startswith("audio/") else 43 if row["mime_type"].startswith("video/") else 3,
                "attachment": None, "indexed_media_path": row["media_path"],
                "indexed_mime_type": row["mime_type"], "indexed_status": "ready", "orphan_media": True,
            }

    def unlinked_downloads(self):
        for paths in self.files_by_size.values():
            for path in paths:
                if path in self.matched_files:
                    continue
                checked = _inside_file(path, self.file_root)
                if not checked:
                    continue
                stat = checked.stat()
                yield {
                    "message_uid": "wechat-download:" + checked.relative_to(self.file_root).as_posix(),
                    "chat_username": "__unlinked_downloads__", "chat_display_name": "未关联会话",
                    "create_time": int(stat.st_mtime), "base_type": 49,
                    "attachment": {"name": checked.name, "size": stat.st_size, "md5": ""},
                    "unlinked_path": str(checked), "download_relative": str(checked.relative_to(self.file_root)),
                }

    def _matched(self, path):
        if path:
            self.matched_files.add(path)
        return path, "ready" if path else "missing_file"

    def find(self, item, previous=None):
        metadata = item["attachment"]
        if item.get("unlinked_path"):
            path = _inside_file(item["unlinked_path"], self.file_root)
            return (path, "ready") if path else (None, "missing_file")
        if metadata is None:
            if item.get("indexed_status") != "ready":
                return None, "not_ready"
            mime = item.get("indexed_mime_type") or ""
            if mime not in MEDIA_TYPES:
                return None, "unsupported_media"
            value = item.get("indexed_media_path")
            if not value:
                return None, "missing_file"
            path = Path(value)
            if not path.is_absolute():
                path = self.media_root.parent / path
            path = _inside_file(path, self.media_root)
            return (path, "ready") if path else (None, "missing_file")
        expected = metadata["md5"]
        if previous and previous.source_rel_path and previous.source_kind == "attachment":
            prior = _inside_file(self.file_root / previous.source_rel_path, self.file_root)
            if prior and (expected or prior.name == metadata["name"]) and _signature(prior.stat()) == previous.source_signature and previous.size_bytes == metadata["size"] and previous.source_md5 == expected:
                return self._matched(prior)
        candidates = self.files_by_size.get(metadata["size"], [])
        if not expected:
            candidates = [path for path in candidates if path.name == metadata["name"]]
            return self._matched(candidates[0]) if len(candidates) == 1 else (None, "ambiguous_file" if candidates else "missing_file")
        for path in candidates:
            signature = None
            try:
                signature = _signature(path.stat())
                cache_key = (str(path), signature, expected)
                matches = self.digest_cache.get(cache_key)
                if matches is None:
                    _read_hash(path, metadata["size"], expected)
                    matches = True
                    self.digest_cache[cache_key] = matches
                if matches:
                    return self._matched(path)
            except (OSError, ValueError):
                if signature is not None:
                    self.digest_cache[(str(path), signature, expected)] = False
        return None, "missing_file"


def _project():
    owner = User.query.filter_by(username=current_app.config.get("SPECIAL_STORAGE_USERNAME", "storage_admin"), role_system="super_admin", status="active", is_activated=True).populate_existing().with_for_update().first()
    if not owner:
        raise ValueError("active configured storage super administrator is required")
    state = WeChatFileSyncState.query.filter_by(instance_id=instance_id()).populate_existing().with_for_update().first()
    if state:
        project = Project.query.filter_by(id=state.project_id).populate_existing().with_for_update().first()
        if not project or project.creator_id != owner.id:
            raise ValueError("WeChat files project ownership changed")
    else:
        key = str(current_app.config.get("WECHAT_FILES_PROJECT_KEY") or "WECHAT_FILES")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", key):
            raise ValueError("invalid WeChat files project key")
        if Project.query.filter_by(key=key).populate_existing().with_for_update().first():
            raise ValueError("WeChat files project key is already used")
        project = Project(name="微信文件", key=key, description="微信已下载附件与已解码媒体，按聊天和月份自动更新。源文件消失不会删除已保存的副本。", creator_id=owner.id)
        db.session.add(project)
        db.session.flush()
        db.session.add(ProjectMember(project_id=project.id, user_id=owner.id, role_project="creator"))
        db.session.add(ProjectSettings(project_id=project.id, guest_visible=False, task_workflow=default_workflow(), task_workflow_updated_at=utcnow()))
        state = WeChatFileSyncState(instance_id=instance_id(), project_id=project.id)
        db.session.add(state)
    root = FileNode.query.filter_by(scope="project", project_id=project.id, parent_id=None, type="folder", deleted_at=None).populate_existing().with_for_update().first()
    if not root:
        root = FileNode(scope="project", project_id=project.id, parent_id=None, type="folder", name="root", created_by=owner.id)
        db.session.add(root)
        db.session.flush()
    db.session.commit()
    return int(project.id), int(root.id), int(owner.id)


def _folder(project_id, parent_id, name, owner_id, marker=None):
    nodes = FileNode.query.filter_by(scope="project", project_id=project_id, parent_id=parent_id, type="folder", deleted_at=None).populate_existing().with_for_update().all()
    found = next((node for node in nodes if node.name.endswith(marker)), None) if marker else next((node for node in nodes if node.name == name), None)
    if found:
        return found
    node = FileNode(scope="project", project_id=project_id, parent_id=parent_id, type="folder", name=name, created_by=owner_id)
    db.session.add(node)
    db.session.flush()
    return node


def _name(item):
    if item["attachment"]:
        return safe_name(item["attachment"]["name"])[:255]
    label = {3: "图片", 34: "语音", 43: "视频", 47: "表情"}.get(int(item["base_type"]), "媒体")
    stamp = dt.datetime.fromtimestamp(int(item.get("create_time") or 0), dt.timezone.utc)
    return label + " " + stamp.strftime("%Y%m%d-%H%M%S") + " [" + source_uid(item["message_uid"])[:12] + "]" + MEDIA_TYPES.get(item.get("indexed_mime_type"), ".bin")


def _kind(item):
    return "unlinked" if item.get("unlinked_path") else "media_orphan" if item.get("orphan_media") else "attachment" if item["attachment"] else "media"


def _parent_for(item, project_id, root_id, owner_id):
    if item.get("unlinked_path") or item.get("orphan_media") or item.get("unlinked_chat"):
        chat = _folder(project_id, root_id, "未关联会话", owner_id)
    else:
        marker = " [" + hashlib.sha256(item["chat_username"].encode("utf-8")).hexdigest()[:16] + "]"
        title = safe_name(item.get("chat_display_name") or item["chat_username"])[:100] + marker
        chat = _folder(project_id, root_id, title, owner_id, marker)
    month = dt.datetime.fromtimestamp(int(item.get("create_time") or 0), dt.timezone.utc).strftime("%Y-%m")
    return _folder(project_id, chat.id, month, owner_id)


def _refresh_aliases(record):
    if record.source_kind != "attachment":
        return
    aliases = WeChatFileImport.query.filter_by(instance_id=instance_id(), source_kind="unlinked", source_rel_path=record.source_rel_path).filter(
        or_(WeChatFileImport.file_node_id == record.file_node_id, WeChatFileImport.file_node_id.is_(None)),
    ).populate_existing().with_for_update().all()
    for alias in aliases:
        alias.file_node_id = record.file_node_id
        alias.source_signature, alias.source_sha256, alias.size_bytes = record.source_signature, record.source_sha256, record.size_bytes
        alias.status = "linked"
        alias.synced_at = record.synced_at


def _record(item):
    row = WeChatFileImport.query.filter_by(instance_id=instance_id(), source_uid=source_uid(item["message_uid"])).populate_existing().with_for_update().first()
    if not row:
        row = WeChatFileImport(instance_id=instance_id(), source_uid=source_uid(item["message_uid"]), message_uid=item["message_uid"], chat_username=item["chat_username"], source_kind=_kind(item), original_name=_name(item))
        db.session.add(row)
    row.last_seen_at = utcnow()
    if item.get("unlinked_path") and not row.source_rel_path:
        row.source_rel_path = item["download_relative"]
    return row


def _copy_one(reader, item, project_id, root_id, owner_id, allow_copy=True):
    project = Project.query.filter_by(id=project_id).populate_existing().with_for_update().one()
    if project.status != "active":
        db.session.rollback()
        return "paused"
    record = _record(item)
    source, status = reader.find(item, record)
    late_parent = (record.source_kind == "media_orphan" and not item.get("orphan_media")) or (
        record.chat_username == "__unlinked_capture__" and not item.get("unlinked_chat")
    )
    if source and _kind(item) == "attachment" and not record.file_node_id:
        source_relative = str(source.relative_to(reader.file_root))
        alias = WeChatFileImport.query.filter_by(instance_id=instance_id(), source_kind="unlinked", source_rel_path=source_relative).populate_existing().with_for_update().first()
        if alias and alias.file_node_id and alias.status != "linked" and not (alias.status == "owner_deleted" and alias.source_signature != _signature(source.stat())):
            # Keep the original path identity as an alias while the real message
            # gains its stable UID. Move this very node; do not leave two copies.
            record.file_node_id = alias.file_node_id
            record.original_name = alias.original_name
            record.source_signature, record.source_sha256, record.size_bytes = alias.source_signature, alias.source_sha256, alias.size_bytes
            record.source_md5 = item["attachment"]["md5"]
            record.source_rel_path = source_relative
            alias.status = "linked"
            late_parent = True
    node = FileNode.query.filter_by(id=record.file_node_id).populate_existing().with_for_update().first() if record.file_node_id else None
    if record.file_node_id and (not node or node.deleted_at is not None):
        record.status = "owner_deleted"
        db.session.commit()
        return "owner_deleted"
    if node and (node.scope != "project" or node.project_id != project_id):
        raise ValueError("imported node left its project")
    if not source:
        record.status = status
        db.session.commit()
        return status
    signature = _signature(source.stat())
    linked_path = record.source_kind == "unlinked" and record.status == "linked"
    if linked_path and record.source_signature != signature:
        # An overwritten download no longer matches its old message MD5. Keep
        # that old chat copy, and give the new unassociated bytes their own node.
        node, record.file_node_id, record.status = None, None, "pending"
        linked_path = False
    previous = db.session.get(StorageObject, node.storage_object_id) if node and node.storage_object_id else None
    expected_md5 = item["attachment"]["md5"] if item["attachment"] else None
    current_name = _name(item)
    if previous and signature == record.source_signature and record.source_md5 == expected_md5 and record.source_sha256 == previous.sha256:
        destination = resolve_object_path(previous.storage_rel_path)
        if Path(destination).is_file() and Path(destination).stat().st_size == previous.size_bytes:
            if not linked_path and node.name == record.original_name and node.name != current_name:
                node.name = current_name
            if not linked_path:
                record.original_name = current_name
            if late_parent:
                node.parent_id = _parent_for(item, project_id, root_id, owner_id).id
            if not item["attachment"] and previous.mime_type != item.get("indexed_mime_type"):
                previous.mime_type = item.get("indexed_mime_type")
            record.source_kind = _kind(item)
            record.chat_username = item["chat_username"]
            record.status = "linked" if linked_path else "ready"
            _refresh_aliases(record)
            db.session.commit()
            return "unchanged"
    if not allow_copy:
        db.session.commit()
        return "deferred"
    relative = new_object_path(project_id)
    incoming = resolve_object_path(relative)
    Path(incoming).parent.mkdir(parents=True, exist_ok=True)
    try:
        metadata = item["attachment"]
        digest, signature, size = _read_hash(source, metadata["size"] if metadata else None, metadata["md5"] if metadata else "", incoming)
        # Follow source metadata corrections and media codec changes unless
        # the owner deliberately chose a different NetDisk name.
        if node and node.name == record.original_name:
            node.name = current_name
        record.original_name = current_name
        mime = mimetypes.guess_type(current_name)[0] if metadata else item.get("indexed_mime_type")
        stored = StorageObject(mime_type=mime or "application/octet-stream", size_bytes=size, storage_rel_path=relative, sha256=digest, created_by=owner_id)
        db.session.add(stored)
        db.session.flush()
        updated = node is not None
        if node:
            node.storage_object_id = stored.id
            if late_parent:
                node.parent_id = _parent_for(item, project_id, root_id, owner_id).id
        else:
            parent = _parent_for(item, project_id, root_id, owner_id)
            node = FileNode(scope="project", project_id=project_id, parent_id=parent.id, type="file", name=record.original_name, storage_object_id=stored.id, created_by=owner_id)
            db.session.add(node)
            db.session.flush()
            record.file_node_id = node.id
        record.source_rel_path = str(source.relative_to(reader.file_root if metadata else reader.media_root))
        record.source_kind = _kind(item)
        record.chat_username = item["chat_username"]
        record.source_signature = signature
        record.source_md5 = expected_md5
        record.source_sha256 = digest
        record.size_bytes = size
        record.status = "ready"
        record.synced_at = utcnow()
        _refresh_aliases(record)
        db.session.commit()
        return "updated" if updated else "imported"
    except Exception:
        db.session.rollback()
        raise
    finally:
        # Named-tree materialization retains its own transaction-safe copy. The
        # source staging file is never the WeChat download and can be removed.
        if Path(incoming).is_file():
            Path(incoming).unlink()


def sync_wechat_files(limit=200):
    if not current_app.config.get("WECHAT_FILES_ENABLED", False):
        raise ValueError("WeChat files synchronization is disabled")
    if not current_app.extensions.get("readable_storage") or not current_app.config.get("READABLE_STORAGE_ENABLED", True):
        raise ValueError("readable project storage is required")
    reader = CaptureFiles()
    # Validate the capture schema/read access before creating any NetDisk rows.
    messages = iter(reader.messages())
    first = next(messages, None)
    project_id, root_id, owner_id = _project()
    counts = {"project_id": project_id, "scanned": 0, "imported": 0, "updated": 0, "failed": 0}
    seen = set()
    for item in itertools.chain([first] if first else [], messages, reader.unlinked_downloads()):
        counts["scanned"] += 1
        seen.add(source_uid(item["message_uid"]))
        try:
            copied = counts["imported"] + counts["updated"]
            status = _copy_one(reader, item, project_id, root_id, owner_id, not limit or copied < limit)
            counts[status] = counts.get(status, 0) + 1
        except (OSError, ValueError):
            db.session.rollback()
            counts["failed"] += 1
            # Avoid logging private chat names, paths, or message contents.
            current_app.logger.warning("WeChat attachment synchronization postponed")
    Project.query.filter_by(id=project_id).populate_existing().with_for_update().one()
    for row in WeChatFileImport.query.filter_by(instance_id=instance_id()).populate_existing().with_for_update().all():
        if row.source_uid not in seen and row.status not in ("owner_deleted", "linked"):
            row.status = "source_removed"
    state = WeChatFileSyncState.query.filter_by(instance_id=instance_id()).one()
    state.last_scan_at = utcnow()
    db.session.commit()
    return counts


def register_wechat_files(app):
    @app.cli.command("sync-wechat-files")
    @click.option("--limit", type=click.IntRange(min=0), default=200, show_default=True, help="Maximum new/changed copies per scan; 0 is unlimited.")
    def command(limit):
        """Copy available capture attachments without modifying WeChat sources."""
        try:
            result = sync_wechat_files(limit)
        except (OSError, ValueError, sqlite3.Error, SQLAlchemyError):
            db.session.rollback()
            raise click.ClickException("WeChat attachment source or private project is unavailable") from None
        click.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
