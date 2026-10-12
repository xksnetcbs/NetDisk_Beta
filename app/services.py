import datetime as dt
import os
import re

from flask import current_app
from flask_jwt_extended import get_jwt_identity
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .storage import new_object_path, resolve_object_path
from .models import (
    FileNode,
    Notification,
    Project,
    ProjectMember,
    ProjectSettings,
    StorageObject,
    User,
    utcnow,
)


def ok(data=None):
    return {"ok": True, "data": {} if data is None else data}


def fail(code, message, status=400):
    return {"ok": False, "error": {"code": code, "message": message}}, status


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def current_user_id():
    v = get_jwt_identity()
    if v is None:
        return None
    return int(v)


def get_user(user_id: int):
    return User.query.get(user_id)


def is_super_admin(user_id: int) -> bool:
    u = get_user(user_id)
    if not u:
        return False
    return u.role_system == "super_admin" and u.status == "active"


ROLE_RANK = {"guest": 0, "user": 1, "admin": 2, "creator": 3}


def project_role(project_id: int, user_id: int):
    if is_super_admin(user_id):
        return "creator"
    p = Project.query.get(int(project_id))
    if p and int(p.creator_id) == int(user_id):
        return "creator"
    m = (
        ProjectMember.query.filter_by(project_id=project_id, user_id=user_id)
        .order_by(ProjectMember.id.desc())
        .first()
    )
    return m.role_project if m else None


def require_project_visible(project_id: int, user_id: int):
    if is_super_admin(user_id):
        return True, "creator"
    role = project_role(project_id, user_id)
    if role:
        return True, role
    settings = ProjectSettings.query.filter_by(project_id=project_id).first()
    if settings and settings.guest_visible:
        return True, "guest"
    return False, None


def require_project_role(project_id: int, user_id: int, min_role: str):
    ok_visible, role = require_project_visible(project_id, user_id)
    if not ok_visible:
        return False, None
    if ROLE_RANK.get(role or "", -1) < ROLE_RANK[min_role]:
        return False, role
    return True, role


def can_edit_project_meta(role: str, user_id: int) -> bool:
    return is_super_admin(user_id) or role == "creator"


def can_manage_project_content(role: str, user_id: int) -> bool:
    return is_super_admin(user_id) or role in ("creator", "admin")


def can_delete_owned(role: str, user_id: int, created_by: int) -> bool:
    if is_super_admin(user_id) or role in ("creator", "admin"):
        return True
    if role == "user":
        return int(created_by) == int(user_id)
    return False


def default_workflow():
    return [
        {"key": "todo", "name": "待办", "color": "#3b82f6"},
        {"key": "doing", "name": "进行中", "color": "#f59e0b"},
        {"key": "done", "name": "已完成", "color": "#10b981"},
    ]


def get_project_settings(project_id: int) -> ProjectSettings:
    s = ProjectSettings.query.filter_by(project_id=project_id).first()
    if not s:
        s = ProjectSettings(
            project_id=project_id,
            guest_visible=False,
            task_workflow=default_workflow(),
            task_workflow_updated_at=utcnow(),
        )
        db.session.add(s)
        db.session.commit()
    if not s.task_workflow:
        s.task_workflow = default_workflow()
        s.task_workflow_updated_at = utcnow()
        db.session.commit()
    return s


def validate_workflow_status(project_id: int, status_key: str) -> bool:
    s = get_project_settings(project_id)
    keys = {x.get("key") for x in (s.task_workflow or [])}
    return status_key in keys


MENTION_ID_RE = re.compile(r"@\{(\d+)\}")
MENTION_NAME_RE = re.compile(r"@([A-Za-z0-9_]{2,32})")


def parse_mentions(text: str):
    if not text:
        return set()
    ids = set(int(x) for x in MENTION_ID_RE.findall(text))
    for name in MENTION_NAME_RE.findall(text):
        u = User.query.filter_by(username=name).first()
        if u:
            ids.add(int(u.id))
    return ids


def notify(user_id: int, ntype: str, title: str, content: str = None, link_url: str = None, meta: dict = None):
    n = Notification(
        user_id=int(user_id),
        type=ntype,
        title=title,
        content=content,
        link_url=link_url,
        meta_json=meta,
        read_at=None,
    )
    db.session.add(n)
    return n


def ensure_storage_root():
    root = current_app.config["STORAGE_ROOT"]
    os.makedirs(root, exist_ok=True)
    os.makedirs(os.path.join(root, "objects"), exist_ok=True)
    return root


def new_object_rel_path(project_id=None):
    return new_object_path(project_id)


def parse_iso_datetime(value: str):
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        return d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def create_storage_object(file_storage, created_by: int, project_id=None):
    rel_path = new_object_rel_path(project_id)
    abs_path = resolve_object_path(rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    file_storage.save(abs_path)
    size_bytes = os.path.getsize(abs_path)
    so = StorageObject(
        mime_type=getattr(file_storage, "mimetype", None),
        size_bytes=size_bytes,
        storage_rel_path=rel_path.replace("\\", "/"),
        sha256=None,
        created_by=int(created_by),
    )
    db.session.add(so)
    db.session.flush()
    return so


def validate_node_scope(scope: str, owner_user_id: int | None, project_id: int | None):
    if scope not in ("personal", "project"):
        return False
    if scope == "personal":
        return owner_user_id is not None and project_id is None
    return project_id is not None and owner_user_id is None


def create_folder(name: str, parent_id: int | None, scope: str, owner_user_id: int | None, project_id: int | None, created_by: int):
    if not validate_node_scope(scope, owner_user_id, project_id):
        return None
    node = FileNode(
        type="folder",
        name=name,
        parent_id=parent_id,
        scope=scope,
        owner_user_id=owner_user_id,
        project_id=project_id,
        storage_object_id=None,
        created_by=int(created_by),
        deleted_at=None,
    )
    db.session.add(node)
    db.session.flush()
    return node


def create_file_node(name: str, parent_id: int | None, scope: str, owner_user_id: int | None, project_id: int | None, storage_object_id: int, created_by: int):
    if not validate_node_scope(scope, owner_user_id, project_id):
        return None
    node = FileNode(
        type="file",
        name=name,
        parent_id=parent_id,
        scope=scope,
        owner_user_id=owner_user_id,
        project_id=project_id,
        storage_object_id=int(storage_object_id),
        created_by=int(created_by),
        deleted_at=None,
    )
    db.session.add(node)
    db.session.flush()
    return node
