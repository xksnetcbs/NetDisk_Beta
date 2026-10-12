import csv
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile

from flask import Blueprint, current_app, request, send_file
from flask_jwt_extended import decode_token, get_jwt, jwt_required
from sqlalchemy import func, or_

from .extensions import db
from .storage import (
    DC_PREFIX,
    dc_storage_root,
    legacy_storage_root,
    object_for_project,
    object_storage_root,
    path_matches_project,
    project_storage_root,
    resolve_object_path,
)
from .auth_sessions import (
    as_utc,
    access_token_for,
    cookie_session,
    create_device_session,
    is_live_session,
    revoke_user_sessions,
    session_duration,
    session_response,
)
from .models import (
    CalendarEvent,
    FileNode,
    InboxMessage,
    InboxRecipient,
    InboxThread,
  InviteCode,
    Notification,
    Project,
    ProjectMember,
    ProjectSettings,
    StorageObject,
    Task,
    TaskAttachment,
    TaskComment,
    TaskWatcher,
    User,
    UserSettings,
    utcnow,
)
from .services import (
    can_delete_owned,
    can_edit_project_meta,
    can_manage_project_content,
    create_file_node,
    create_folder,
    create_storage_object,
    current_user_id,
    ensure_storage_root,
    fail,
    get_project_settings,
    hash_password,
    is_super_admin,
    new_object_rel_path,
    notify,
    ok,
    parse_mentions,
    parse_iso_datetime,
    project_role,
    require_project_role,
    require_project_visible,
    validate_workflow_status,
    verify_password,
)

api_bp = Blueprint("api", __name__)
ZIP_TASKS = {}
ZIP_TASK_LOCK = threading.Lock()


def to_user(u: User):
    return {
        "id": int(u.id),
        "username": u.username,
        "display_name": u.display_name,
        "email": u.email,
        "role_system": u.role_system,
        "status": u.status,
        "invite_code": u.invite_code,
        "is_activated": bool(u.is_activated),
        "avatar_file_id": u.avatar_file_id,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "created_at": u.created_at.isoformat(),
        "updated_at": u.updated_at.isoformat(),
    }


def to_user_brief(u: User):
    return {
        "id": int(u.id),
        "username": u.username,
        "display_name": u.display_name,
    }


def user_label(u: User | None):
    if not u:
        return "未知用户"
    dn = (u.display_name or "").strip()
    un = (u.username or "").strip()
    nick = dn or un or f"#{int(u.id)}"
    uname = un or nick
    return f"{nick} ({uname})"


def ensure_project_group_thread(project_id: int, created_by: int):
    db.session.flush()
    subject = f"project:{int(project_id)}"
    t = InboxThread.query.filter_by(type="project_group", subject=subject).first()
    if not t:
        t = InboxThread(type="project_group", subject=subject, created_by=int(created_by or 0))
        db.session.add(t)
        db.session.flush()
    members = ProjectMember.query.filter_by(project_id=int(project_id)).all()
    member_ids = {int(m.user_id) for m in members}
    if member_ids:
        all_recs = InboxRecipient.query.filter_by(thread_id=int(t.id)).all()
        rec_ids = {int(x.user_id) for x in all_recs}
        for uid in member_ids - rec_ids:
            db.session.add(InboxRecipient(thread_id=int(t.id), user_id=int(uid), last_read_at=None))
        extra = [x for x in all_recs if int(x.user_id) not in member_ids]
        for x in extra:
            db.session.delete(x)
    return t


def add_project_group_message(project_id: int, sender_id: int, content_md: str):
    t = ensure_project_group_thread(int(project_id), int(sender_id))
    db.session.add(InboxMessage(thread_id=int(t.id), sender_id=int(sender_id), content_md=content_md or ""))
    t.updated_at = utcnow()
    return int(t.id)


def add_project_system_message(project_id: int, content_md: str, actor_user_id: int | None = None):
    actor = User.query.get(int(actor_user_id)) if actor_user_id else None
    content = content_md or ""
    if actor_user_id:
        content = f"{user_label(actor)}：{content}"
    t = ensure_project_group_thread(int(project_id), int(actor_user_id or 0))
    db.session.add(InboxMessage(thread_id=int(t.id), sender_id=0, content_md=content))
    t.updated_at = utcnow()
    return int(t.id)


def to_project(p: Project, role: str | None):
    return {
        "id": int(p.id),
        "name": p.name,
        "key": p.key,
        "description": p.description,
        "creator_id": int(p.creator_id),
        "status": p.status,
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "end_date": p.end_date.isoformat() if p.end_date else None,
        "role": role,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


def to_task(t: Task):
    return {
        "id": int(t.id),
        "project_id": int(t.project_id),
        "title": t.title,
        "description_md": t.description_md,
        "status": t.status,
        "priority": t.priority,
        "assignee_id": int(t.assignee_id) if t.assignee_id else None,
        "reporter_id": int(t.reporter_id),
        "start_at": t.start_at.isoformat() if t.start_at else None,
        "due_at": t.due_at.isoformat() if t.due_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }


def to_file_node(n: FileNode):
    data = {
        "id": int(n.id),
        "type": n.type,
        "name": n.name,
        "parent_id": int(n.parent_id) if n.parent_id else None,
        "scope": n.scope,
        "owner_user_id": int(n.owner_user_id) if n.owner_user_id else None,
        "project_id": int(n.project_id) if n.project_id else None,
        "storage_object_id": int(n.storage_object_id) if n.storage_object_id else None,
        "created_by": int(n.created_by),
        "deleted_at": n.deleted_at.isoformat() if n.deleted_at else None,
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat(),
    }
    if n.type == "file" and n.storage_object_id:
        so = StorageObject.query.get(int(n.storage_object_id))
        if so:
            data["mime_type"] = so.mime_type
            data["size_bytes"] = int(so.size_bytes or 0)
    return data


def ensure_personal_root(user_id: int):
    root = (
        FileNode.query.filter_by(scope="personal", owner_user_id=user_id, parent_id=None, deleted_at=None, type="folder")
        .order_by(FileNode.id.asc())
        .first()
    )
    if root:
        return root
    root = create_folder("root", None, "personal", user_id, None, user_id)
    db.session.commit()
    return root


def ensure_project_root(project_id: int, created_by: int):
    root = (
        FileNode.query.filter_by(scope="project", project_id=project_id, parent_id=None, deleted_at=None, type="folder")
        .order_by(FileNode.id.asc())
        .first()
    )
    if root:
        return root
    root = create_folder("root", None, "project", None, project_id, created_by)
    db.session.commit()
    return root


@api_bp.post("/auth/bootstrap")
def auth_bootstrap():
    if User.query.count() > 0:
        return fail("CONFLICT", "系统已初始化", 409)
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    display_name = (body.get("display_name") or username).strip() or username
    if len(username) < 2 or len(password) < 6:
        return fail("VALIDATION_ERROR", "用户名或密码不符合要求", 400)
    u = User(
        username=username,
        email=None,
        password_hash=hash_password(password),
        display_name=display_name,
        avatar_file_id=None,
        role_system="super_admin",
        status="active",
        invite_code=None,
        is_activated=True,
        last_login_at=None,
    )
    db.session.add(u)
    db.session.flush()
    s = UserSettings(user_id=int(u.id))
    db.session.add(s)
    session, raw_token = create_device_session(u.id)
    db.session.commit()
    return session_response(ok({"access_token": access_token_for(session), "user": to_user(u)}), raw_token)


@api_bp.post("/auth/login")
def auth_login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    u = User.query.filter_by(username=username).first()
    if not u or not verify_password(password, u.password_hash):
        return fail("LOGIN_FAILED", "用户名或密码错误", 401)
    if u.status != "active":
        return fail("ACCOUNT_DISABLED", "账号已被禁用", 403)
    if not bool(getattr(u, "is_activated", False)):
        return fail("ACCOUNT_NOT_ACTIVATED", "用户未激活", 403)
    u.last_login_at = utcnow()
    session, raw_token = create_device_session(u.id)
    db.session.commit()
    return session_response(ok({"access_token": access_token_for(session), "user": to_user(u)}), raw_token)


@api_bp.post("/auth/refresh")
def auth_refresh():
    # Custom headers require a CORS preflight, preventing cookie-only cross-site POSTs.
    if request.headers.get("X-DCP-Session") != "1":
        return fail("FORBIDDEN", "会话请求无效", 403)
    session, raw_token = cookie_session()
    if not is_live_session(session):
        data, status = fail("UNAUTHORIZED", "请重新登录", 401)
        return session_response(data, clear=True, status=status)
    u = db.session.get(User, int(session.user_id))
    if not u or u.status != "active" or not u.is_activated:
        revoke_user_sessions(session.user_id)
        db.session.commit()
        data, status = fail("ACCOUNT_DISABLED", "账号不可登录", 401)
        return session_response(data, clear=True, status=status)
    # Keep the same cookie secret so parallel requests and browser tabs can renew safely.
    session.expires_at = utcnow() + session_duration()
    db.session.commit()
    return session_response(ok({"access_token": access_token_for(session), "user": to_user(u)}), raw_token)


@api_bp.post("/auth/logout")
def auth_logout():
    if request.headers.get("X-DCP-Session") != "1":
        return fail("FORBIDDEN", "会话请求无效", 403)
    session, _ = cookie_session()
    if session and session.revoked_at is None:
        session.revoked_at = utcnow()
        db.session.commit()
    return session_response(ok({}), clear=True)


@api_bp.post("/auth/register")
def auth_register():
    body = request.get_json(silent=True) or {}
    invite_code = (body.get("invite_code") or "").strip()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    display_name = (body.get("display_name") or username).strip() or username
    if not invite_code:
        return fail("VALIDATION_ERROR", "邀请码必填", 400)
    if len(username) < 2 or len(password) < 6:
        return fail("VALIDATION_ERROR", "用户名或密码不符合要求", 400)
    if User.query.filter_by(username=username).first():
        return fail("CONFLICT", "用户名已存在", 409)

    code_row = InviteCode.query.filter_by(code=invite_code).first()
    if not code_row or not bool(code_row.enabled):
        return fail("INVITE_CODE_INVALID", "邀请码无效", 400)
    max_uses = int(code_row.max_uses) if code_row.max_uses is not None else None
    used = int(code_row.used_count or 0)
    if max_uses is not None and used >= max_uses:
        return fail("INVITE_CODE_INVALID", "邀请码无效", 400)

    u = User(
        username=username,
        email=None,
        password_hash=hash_password(password),
        display_name=display_name,
        avatar_file_id=None,
        role_system="user",
        status="active",
        invite_code=invite_code,
        is_activated=False,
        last_login_at=None,
    )
    db.session.add(u)
    db.session.flush()
    db.session.add(UserSettings(user_id=int(u.id)))
    code_row.used_count = int(code_row.used_count or 0) + 1

    admins = User.query.filter_by(role_system="super_admin", status="active").all()
    for a in admins:
        if not bool(getattr(a, "is_activated", True)):
            continue
        subject = "准入审核"
        t = InboxThread.query.filter_by(type="system", created_by=int(a.id), subject=subject).first()
        if not t:
            t = InboxThread(type="system", subject=subject, created_by=int(a.id))
            db.session.add(t)
            db.session.flush()
            db.session.add(InboxRecipient(thread_id=int(t.id), user_id=int(a.id), last_read_at=None))
        else:
            r = InboxRecipient.query.filter_by(thread_id=int(t.id), user_id=int(a.id)).first()
            if not r:
                db.session.add(InboxRecipient(thread_id=int(t.id), user_id=int(a.id), last_read_at=None))
        db.session.add(InboxMessage(thread_id=int(t.id), sender_id=int(a.id), content_md=f"发信人: Server\n内容：用户{u.username}等待审核，请前往批准"))
        t.updated_at = utcnow()
        notify(int(a.id), "system", "准入审核", f"发信人: Server\n内容：用户{u.username}等待审核，请前往批准", "/admin", {"user_id": int(u.id)})
    notify(int(u.id), "user_register_pending", "注册成功，等待管理员审核", None, None, None)
    db.session.commit()
    return ok({"pending_approval": True})


@api_bp.get("/auth/me")
@jwt_required()
def auth_me():
    uid = current_user_id()
    u = User.query.get(uid)
    if not u:
        return fail("UNAUTHORIZED", "未登录", 401)
    if u.status != "active" or not u.is_activated:
        return fail("ACCOUNT_DISABLED", "账号不可登录", 401)
    if get_jwt().get("auth_session") is None:
        session, raw_token = create_device_session(u.id)
        db.session.commit()
        return session_response(ok({"access_token": access_token_for(session), "user": to_user(u)}), raw_token)
    return session_response(ok({"user": to_user(u)}))


@api_bp.post("/auth/change-password")
@jwt_required()
def auth_change_password():
    uid = current_user_id()
    u = User.query.get(uid)
    if not u:
        return fail("UNAUTHORIZED", "未登录", 401)
    body = request.get_json(silent=True) or {}
    old_password = body.get("old_password") or ""
    new_password = body.get("new_password") or ""
    if not verify_password(old_password, u.password_hash):
        return fail("LOGIN_FAILED", "旧密码错误", 400)
    if len(new_password) < 6:
        return fail("PASSWORD_WEAK", "新密码过短", 400)
    u.password_hash = hash_password(new_password)
    revoke_user_sessions(u.id)
    db.session.commit()
    return session_response(ok({}), clear=True)


@api_bp.get("/users")
@jwt_required()
def users_list():
    uid = current_user_id()
    if not is_super_admin(uid):
        return fail("FORBIDDEN", "无权限", 403)
    page = int(request.args.get("page", "1"))
    page_size = min(int(request.args.get("page_size", "20")), 100)
    q = User.query.order_by(User.id.desc())
    activated = request.args.get("activated")
    if activated in ("0", "1"):
        q = q.filter(User.is_activated == (activated == "1"))
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    total = q.count()
    return ok({"items": [to_user(x) for x in items], "total": total, "page": page, "page_size": page_size})


@api_bp.get("/users/search")
@jwt_required()
def users_search():
    q0 = (request.args.get("q") or "").strip()
    page = int(request.args.get("page", "1"))
    page_size = min(int(request.args.get("page_size", "200")), 5000)
    q = User.query.filter(User.status == "active", User.is_activated == True)
    if q0:
        like = f"%{q0}%"
        q = q.filter(or_(User.username.ilike(like), User.display_name.ilike(like)))
    q = q.order_by(User.id.asc())
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    total = q.count()
    return ok({"items": [to_user_brief(x) for x in items], "total": total, "page": page, "page_size": page_size})


@api_bp.post("/users")
@jwt_required()
def users_create():
    uid = current_user_id()
    if not is_super_admin(uid):
        return fail("FORBIDDEN", "无权限", 403)
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    display_name = (body.get("display_name") or username).strip() or username
    role_system = body.get("role_system") or "user"
    if role_system not in ("user", "super_admin"):
        return fail("VALIDATION_ERROR", "角色非法", 400)
    if len(username) < 2 or len(password) < 6:
        return fail("VALIDATION_ERROR", "用户名或密码不符合要求", 400)
    if User.query.filter_by(username=username).first():
        return fail("CONFLICT", "用户名已存在", 409)
    u = User(
        username=username,
        email=(body.get("email") or None),
        password_hash=hash_password(password),
        display_name=display_name,
        avatar_file_id=None,
        role_system=role_system,
        status="active",
        invite_code=None,
        is_activated=True,
        last_login_at=None,
    )
    db.session.add(u)
    db.session.flush()
    db.session.add(UserSettings(user_id=int(u.id)))
    db.session.commit()
    return ok({"user": to_user(u)})


@api_bp.patch("/users/<int:user_id>")
@jwt_required()
def users_patch(user_id: int):
    uid = current_user_id()
    body = request.get_json(silent=True) or {}
    u = User.query.get(user_id)
    if not u:
        return fail("NOT_FOUND", "用户不存在", 404)
    if not (is_super_admin(uid) or int(uid) == int(user_id)):
        return fail("FORBIDDEN", "无权限", 403)
    if "display_name" in body and (is_super_admin(uid) or int(uid) == int(user_id)):
        v = (body.get("display_name") or "").strip()
        if v:
            u.display_name = v
    if "email" in body and (is_super_admin(uid) or int(uid) == int(user_id)):
        v0 = (body.get("email") or "").strip()
        if not v0:
            u.email = None
        else:
            exists = User.query.filter(User.email == v0, User.id != int(user_id)).first()
            if exists:
                return fail("CONFLICT", "邮箱已存在", 409)
            u.email = v0
    if is_super_admin(uid):
        if "status" in body and body.get("status") in ("active", "disabled"):
            u.status = body.get("status")
        if "role_system" in body and body.get("role_system") in ("user", "super_admin"):
            u.role_system = body.get("role_system")
        if "is_activated" in body:
            u.is_activated = bool(body.get("is_activated"))
        if u.status != "active" or not u.is_activated:
            revoke_user_sessions(u.id)
    db.session.commit()
    return ok({"user": to_user(u)})


@api_bp.get("/projects")
@jwt_required()
def projects_list():
    uid = current_user_id()
    page = int(request.args.get("page", "1"))
    page_size = min(int(request.args.get("page_size", "20")), 100)
    owned_projects = (
        Project.query.filter(Project.creator_id == int(uid))
        .order_by(Project.id.desc())
        .all()
    )
    member_ids = (
        db.session.query(ProjectMember.project_id)
        .filter(ProjectMember.user_id == uid)
        .subquery()
    )
    visible_projects = (
        Project.query.filter(Project.id.in_(member_ids))
        .order_by(Project.id.desc())
        .all()
    )
    guest_visible = (
        db.session.query(ProjectSettings.project_id)
        .filter(ProjectSettings.guest_visible == True)
        .subquery()
    )
    guest_projects = (
        Project.query.filter(Project.id.in_(guest_visible))
        .order_by(Project.id.desc())
        .all()
    )
    merged = {}
    for p in owned_projects:
        merged[int(p.id)] = (p, "creator")
    for p in visible_projects:
        merged[int(p.id)] = (p, project_role(int(p.id), uid))
    for p in guest_projects:
        if int(p.id) not in merged:
            merged[int(p.id)] = (p, "guest")
    items_all = list(merged.values())
    items_all.sort(key=lambda x: int(x[0].id), reverse=True)
    total = len(items_all)
    items = items_all[(page - 1) * page_size : page * page_size]
    return ok({"items": [to_project(p, r) for (p, r) in items], "total": total, "page": page, "page_size": page_size})


@api_bp.post("/projects")
@jwt_required()
def projects_create():
    uid = current_user_id()
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    key = (body.get("key") or "").strip()
    if not name or not key:
        return fail("VALIDATION_ERROR", "name/key 必填", 400)
    if Project.query.filter_by(key=key).first():
        return fail("CONFLICT", "key 已存在", 409)
    p = Project(
        name=name,
        key=key,
        description=body.get("description"),
        creator_id=int(uid),
        status="active",
        start_date=None,
        end_date=None,
    )
    db.session.add(p)
    db.session.flush()
    db.session.add(ProjectMember(project_id=int(p.id), user_id=int(uid), role_project="creator"))
    db.session.commit()
    get_project_settings(int(p.id))
    ensure_project_root(int(p.id), int(uid))
    return ok({"project": to_project(p, "creator")})


@api_bp.get("/projects/<int:project_id>")
@jwt_required()
def projects_get(project_id: int):
    uid = current_user_id()
    ok_vis, role = require_project_visible(project_id, uid)
    if not ok_vis:
        return fail("PROJECT_FORBIDDEN", "无权限访问该项目", 403)
    p = Project.query.get(project_id)
    if not p:
        return fail("NOT_FOUND", "项目不存在", 404)
    return ok({"project": to_project(p, role)})


@api_bp.patch("/projects/<int:project_id>")
@jwt_required()
def projects_patch(project_id: int):
    uid = current_user_id()
    ok_vis, role = require_project_visible(project_id, uid)
    if not ok_vis:
        return fail("PROJECT_FORBIDDEN", "无权限", 403)
    if not can_edit_project_meta(role, uid):
        return fail("FORBIDDEN", "无权限修改项目本身信息", 403)
    p = Project.query.get(project_id)
    if not p:
        return fail("NOT_FOUND", "项目不存在", 404)
    body = request.get_json(silent=True) or {}
    old_name = p.name
    old_key = p.key
    old_desc = p.description
    if "name" in body:
        v = (body.get("name") or "").strip()
        if v:
            p.name = v
    if "key" in body:
        v = (body.get("key") or "").strip()
        if v and v != p.key:
            if Project.query.filter_by(key=v).first():
                return fail("CONFLICT", "key 已存在", 409)
            p.key = v
    if "description" in body:
        p.description = body.get("description")
    changed = []
    if p.name != old_name:
        changed.append("名称")
    if p.key != old_key:
        changed.append("Key")
    if p.description != old_desc:
        changed.append("描述")
    if changed:
        add_project_system_message(int(project_id), f"修改项目信息：{', '.join(changed)}", int(uid))
    db.session.commit()
    return ok({"project": to_project(p, role)})


@api_bp.post("/projects/<int:project_id>/archive")
@jwt_required()
def projects_archive(project_id: int):
    uid = current_user_id()
    ok_vis, role = require_project_visible(project_id, uid)
    if not ok_vis:
        return fail("PROJECT_FORBIDDEN", "无权限", 403)
    if not can_edit_project_meta(role, uid):
        return fail("FORBIDDEN", "无权限归档项目", 403)
    p = Project.query.get(project_id)
    if not p:
        return fail("NOT_FOUND", "项目不存在", 404)
    p.status = "archived"
    db.session.commit()
    return ok({})


@api_bp.post("/projects/<int:project_id>/unarchive")
@jwt_required()
def projects_unarchive(project_id: int):
    uid = current_user_id()
    ok_vis, role = require_project_visible(project_id, uid)
    if not ok_vis:
        return fail("PROJECT_FORBIDDEN", "无权限", 403)
    if not can_edit_project_meta(role, uid):
        return fail("FORBIDDEN", "无权限取消归档", 403)
    p = Project.query.get(project_id)
    if not p:
        return fail("NOT_FOUND", "项目不存在", 404)
    p.status = "active"
    db.session.commit()
    return ok({})


def project_manage_user_stats(project_id: int, actor_user_id: int):
    tasks_reported = {
        int(uid): int(cnt)
        for uid, cnt in db.session.query(Task.reporter_id, func.count(Task.id))
        .filter(Task.project_id == int(project_id))
        .group_by(Task.reporter_id)
        .all()
    }
    tasks_completed = {
        int(uid): int(cnt)
        for uid, cnt in db.session.query(Task.assignee_id, func.count(Task.id))
        .filter(Task.project_id == int(project_id), Task.assignee_id.isnot(None), Task.completed_at.isnot(None))
        .group_by(Task.assignee_id)
        .all()
    }
    files_uploaded = {
        int(uid): int(cnt)
        for uid, cnt in db.session.query(FileNode.created_by, func.count(FileNode.id))
        .filter(
            FileNode.project_id == int(project_id),
            FileNode.type == "file",
            FileNode.deleted_at.is_(None),
        )
        .group_by(FileNode.created_by)
        .all()
    }
    t = ensure_project_group_thread(int(project_id), int(actor_user_id))
    messages_sent = {
        int(uid): int(cnt)
        for uid, cnt in db.session.query(InboxMessage.sender_id, func.count(InboxMessage.id))
        .filter(InboxMessage.thread_id == int(t.id), InboxMessage.sender_id != 0)
        .group_by(InboxMessage.sender_id)
        .all()
    }
    return tasks_reported, tasks_completed, files_uploaded, messages_sent


@api_bp.get("/projects/<int:project_id>/manage/overview")
@jwt_required()
def project_manage_overview(project_id: int):
    uid = current_user_id()
    ok_role, role = require_project_role(project_id, uid, "admin")
    if not ok_role:
        return fail("FORBIDDEN", "无权限", 403)
    p = Project.query.get(project_id)
    if not p:
        return fail("NOT_FOUND", "项目不存在", 404)

    tasks_total = int(Task.query.filter_by(project_id=int(project_id)).count())
    tasks_done = int(Task.query.filter_by(project_id=int(project_id)).filter(Task.completed_at.isnot(None)).count())
    tasks_todo = max(0, tasks_total - tasks_done)

    files_count = int(
        FileNode.query.filter(
            FileNode.project_id == int(project_id),
            FileNode.type == "file",
            FileNode.deleted_at.is_(None),
        ).count()
    )
    storage_bytes = int(
        db.session.query(func.coalesce(func.sum(StorageObject.size_bytes), 0))
        .select_from(FileNode)
        .join(StorageObject, StorageObject.id == FileNode.storage_object_id)
        .filter(
            FileNode.project_id == int(project_id),
            FileNode.type == "file",
            FileNode.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )

    return ok(
        {
            "project": to_project(p, role),
            "my_role": role,
            "stats": {
                "tasks_total": tasks_total,
                "tasks_todo": tasks_todo,
                "tasks_done": tasks_done,
                "files_count": files_count,
                "storage_bytes": storage_bytes,
            },
        }
    )


@api_bp.get("/projects/<int:project_id>/manage/users")
@jwt_required()
def project_manage_users(project_id: int):
    uid = current_user_id()
    ok_role, role = require_project_role(project_id, uid, "admin")
    if not ok_role:
        return fail("FORBIDDEN", "无权限", 403)

    members = ProjectMember.query.filter_by(project_id=int(project_id)).order_by(ProjectMember.id.asc()).all()
    user_ids = [int(m.user_id) for m in members]
    users = {int(u.id): u for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}

    tasks_reported, tasks_completed, files_uploaded, messages_sent = project_manage_user_stats(int(project_id), int(uid))

    items = []
    for m in members:
        u = users.get(int(m.user_id))
        items.append(
            {
                "user": to_user(u) if u else {"id": int(m.user_id)},
                "role_project": m.role_project,
                "joined_at": m.joined_at.isoformat(),
                "tasks_reported": int(tasks_reported.get(int(m.user_id), 0)),
                "tasks_completed": int(tasks_completed.get(int(m.user_id), 0)),
                "files_uploaded": int(files_uploaded.get(int(m.user_id), 0)),
                "messages_sent": int(messages_sent.get(int(m.user_id), 0)),
            }
        )
    return ok({"items": items, "my_role": role})


@api_bp.get("/projects/<int:project_id>/manage/users/export")
@jwt_required()
def project_manage_users_export(project_id: int):
    uid = current_user_id()
    ok_role, _ = require_project_role(project_id, uid, "admin")
    if not ok_role:
        return fail("FORBIDDEN", "无权限", 403)

    p = Project.query.get(project_id)
    if not p:
        return fail("NOT_FOUND", "项目不存在", 404)

    members = ProjectMember.query.filter_by(project_id=int(project_id)).order_by(ProjectMember.id.asc()).all()
    user_ids = [int(m.user_id) for m in members]
    users = {int(u.id): u for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}
    tasks_reported, tasks_completed, files_uploaded, messages_sent = project_manage_user_stats(int(project_id), int(uid))

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "user_id",
            "username",
            "display_name",
            "status",
            "role_project",
            "joined_at",
            "tasks_reported",
            "tasks_completed",
            "files_uploaded",
            "messages_sent",
        ]
    )
    for m in members:
        u = users.get(int(m.user_id))
        w.writerow(
            [
                int(m.user_id),
                (u.username if u else ""),
                (u.display_name if u else ""),
                (u.status if u else ""),
                m.role_project,
                m.joined_at.isoformat(),
                int(tasks_reported.get(int(m.user_id), 0)),
                int(tasks_completed.get(int(m.user_id), 0)),
                int(files_uploaded.get(int(m.user_id), 0)),
                int(messages_sent.get(int(m.user_id), 0)),
            ]
        )

    data = buf.getvalue().encode("utf-8-sig")
    return send_file(
        io.BytesIO(data),
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name=f"{p.key or 'project'}_users.csv",
    )


@api_bp.get("/projects/<int:project_id>/members")
@jwt_required()
def project_members_list(project_id: int):
    uid = current_user_id()
    ok_vis, role = require_project_visible(project_id, uid)
    if not ok_vis:
        return fail("PROJECT_FORBIDDEN", "无权限", 403)
    members = ProjectMember.query.filter_by(project_id=project_id).order_by(ProjectMember.id.asc()).all()
    users = {int(u.id): u for u in User.query.filter(User.id.in_([m.user_id for m in members])).all()}
    items = []
    for m in members:
        u = users.get(int(m.user_id))
        items.append(
            {
                "user": to_user(u) if u else {"id": int(m.user_id)},
                "role_project": m.role_project,
                "joined_at": m.joined_at.isoformat(),
            }
        )
    return ok({"items": items, "my_role": role})


@api_bp.post("/projects/<int:project_id>/members")
@jwt_required()
def project_members_add(project_id: int):
    uid = current_user_id()
    ok_role, role = require_project_role(project_id, uid, "admin")
    if not ok_role:
        return fail("FORBIDDEN", "无权限", 403)
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    role_project = body.get("role_project") or "user"
    if role_project not in ("creator", "admin", "user", "guest"):
        return fail("VALIDATION_ERROR", "角色非法", 400)
    if not user_id:
        return fail("VALIDATION_ERROR", "user_id 必填", 400)
    if ProjectMember.query.filter_by(project_id=project_id, user_id=int(user_id)).first():
        return fail("CONFLICT", "用户已在项目中", 409)
    if role_project == "creator" and not is_super_admin(uid) and role != "creator":
        return fail("FORBIDDEN", "仅创建者可设为创建者", 403)
    db.session.add(ProjectMember(project_id=project_id, user_id=int(user_id), role_project=role_project))
    tu = User.query.get(int(user_id))
    add_project_system_message(int(project_id), f"邀请成员：{user_label(tu)}，角色：{role_project}", int(uid))
    db.session.commit()
    return ok({})


@api_bp.patch("/projects/<int:project_id>/members/<int:user_id>")
@jwt_required()
def project_members_patch(project_id: int, user_id: int):
    uid = current_user_id()
    ok_role, role = require_project_role(project_id, uid, "admin")
    if not ok_role:
        return fail("FORBIDDEN", "无权限", 403)
    body = request.get_json(silent=True) or {}
    role_project = body.get("role_project")
    if role_project not in ("creator", "admin", "user", "guest"):
        return fail("VALIDATION_ERROR", "角色非法", 400)
    m = ProjectMember.query.filter_by(project_id=project_id, user_id=user_id).first()
    if not m:
        return fail("NOT_FOUND", "成员不存在", 404)
    old_role = m.role_project
    if m.role_project == "creator" and role_project != "creator":
        if not is_super_admin(uid) and role != "creator":
            return fail("FORBIDDEN", "仅创建者可调整创建者角色", 403)
    if role_project == "creator" and not is_super_admin(uid) and role != "creator":
        return fail("FORBIDDEN", "仅创建者可设为创建者", 403)
    m.role_project = role_project
    if old_role != role_project:
        tu = User.query.get(int(user_id))
        add_project_system_message(int(project_id), f"修改成员权限：{user_label(tu)}，{old_role} -> {role_project}", int(uid))
    db.session.commit()
    return ok({})


@api_bp.delete("/projects/<int:project_id>/members/<int:user_id>")
@jwt_required()
def project_members_remove(project_id: int, user_id: int):
    uid = current_user_id()
    ok_role, role = require_project_role(project_id, uid, "admin")
    if not ok_role:
        return fail("FORBIDDEN", "无权限", 403)
    m = ProjectMember.query.filter_by(project_id=project_id, user_id=user_id).first()
    if not m:
        return fail("NOT_FOUND", "成员不存在", 404)
    if m.role_project == "creator":
        return fail("FORBIDDEN", "不能移除创建者", 403)
    db.session.delete(m)
    tu = User.query.get(int(user_id))
    add_project_system_message(int(project_id), f"移除成员：{user_label(tu)}", int(uid))
    db.session.commit()
    return ok({})


@api_bp.get("/projects/<int:project_id>/group-messages")
@jwt_required()
def project_group_messages_list(project_id: int):
    uid = current_user_id()
    ok_vis, role = require_project_visible(project_id, uid)
    if not ok_vis:
        return fail("PROJECT_FORBIDDEN", "无权限", 403)
    t = ensure_project_group_thread(int(project_id), int(uid))
    items = InboxMessage.query.filter_by(thread_id=int(t.id)).order_by(InboxMessage.id.asc()).all()
    sender_ids = {int(x.sender_id) for x in items if int(x.sender_id) != 0}
    users = {int(u.id): u for u in User.query.filter(User.id.in_(list(sender_ids))).all()} if sender_ids else {}
    out = []
    for x in items:
        sid = int(x.sender_id)
        if sid == 0:
            out.append({"id": int(x.id), "sender_id": 0, "sender_name": "系统", "is_system": True, "content_md": x.content_md, "created_at": x.created_at.isoformat()})
        else:
            su = users.get(sid)
            out.append({"id": int(x.id), "sender_id": sid, "sender_name": (su.display_name if su else None), "is_system": False, "content_md": x.content_md, "created_at": x.created_at.isoformat()})
    return ok({"thread_id": int(t.id), "items": out, "my_role": role})


@api_bp.post("/projects/<int:project_id>/group-messages")
@jwt_required()
def project_group_messages_create(project_id: int):
    uid = current_user_id()
    ok_role, role = require_project_role(project_id, uid, "user")
    if not ok_role:
        return fail("FORBIDDEN", "无权限", 403)
    body = request.get_json(silent=True) or {}
    content_md = body.get("content_md") or ""
    if not content_md.strip():
        return fail("VALIDATION_ERROR", "content_md 必填", 400)
    thread_id = add_project_group_message(int(project_id), int(uid), content_md)
    mention_ids = parse_mentions(content_md)
    for mid in mention_ids:
        if int(mid) != int(uid):
            notify(int(mid), "mention", "你在群组消息中被提及", None, f"/projects/{project_id}", {"project_id": int(project_id), "thread_id": int(thread_id)})
    db.session.commit()
    return ok({"thread_id": int(thread_id), "my_role": role})


@api_bp.get("/projects/<int:project_id>/settings")
@jwt_required()
def project_settings_get(project_id: int):
    uid = current_user_id()
    ok_vis, role = require_project_visible(project_id, uid)
    if not ok_vis:
        return fail("PROJECT_FORBIDDEN", "无权限", 403)
    s = get_project_settings(project_id)
    return ok({"settings": {"guest_visible": bool(s.guest_visible), "task_workflow": s.task_workflow}, "my_role": role})


@api_bp.patch("/projects/<int:project_id>/settings")
@jwt_required()
def project_settings_patch(project_id: int):
    uid = current_user_id()
    ok_role, role = require_project_role(project_id, uid, "admin")
    if not ok_role:
        return fail("FORBIDDEN", "无权限", 403)
    s = get_project_settings(project_id)
    body = request.get_json(silent=True) or {}
    if "guest_visible" in body:
        s.guest_visible = bool(body.get("guest_visible"))
    if "task_workflow" in body:
        wf = body.get("task_workflow")
        if not isinstance(wf, list) or len(wf) == 0:
            return fail("VALIDATION_ERROR", "task_workflow 非法", 400)
        keys = [x.get("key") for x in wf if isinstance(x, dict)]
        if any((not k or not isinstance(k, str)) for k in keys):
            return fail("VALIDATION_ERROR", "task_workflow.key 非法", 400)
        if len(set(keys)) != len(keys):
            return fail("VALIDATION_ERROR", "task_workflow.key 重复", 400)
        s.task_workflow = wf
        s.task_workflow_updated_at = utcnow()
    db.session.commit()
    return ok({"settings": {"guest_visible": bool(s.guest_visible), "task_workflow": s.task_workflow}})


@api_bp.get("/projects/<int:project_id>/workflow")
@jwt_required()
def project_workflow_get(project_id: int):
    uid = current_user_id()
    ok_vis, _ = require_project_visible(project_id, uid)
    if not ok_vis:
        return fail("PROJECT_FORBIDDEN", "无权限", 403)
    s = get_project_settings(project_id)
    return ok({"workflow": s.task_workflow, "updated_at": s.task_workflow_updated_at.isoformat() if s.task_workflow_updated_at else None})


@api_bp.put("/projects/<int:project_id>/workflow")
@jwt_required()
def project_workflow_put(project_id: int):
    uid = current_user_id()
    ok_role, _ = require_project_role(project_id, uid, "admin")
    if not ok_role:
        return fail("FORBIDDEN", "无权限", 403)
    body = request.get_json(silent=True) or {}
    wf = body.get("workflow")
    if not isinstance(wf, list) or len(wf) == 0:
        return fail("VALIDATION_ERROR", "workflow 非法", 400)
    keys = [x.get("key") for x in wf if isinstance(x, dict)]
    if any((not k or not isinstance(k, str)) for k in keys):
        return fail("VALIDATION_ERROR", "workflow.key 非法", 400)
    if len(set(keys)) != len(keys):
        return fail("VALIDATION_ERROR", "workflow.key 重复", 400)
    s = get_project_settings(project_id)
    s.task_workflow = wf
    s.task_workflow_updated_at = utcnow()
    db.session.commit()
    return ok({"workflow": s.task_workflow})


@api_bp.get("/projects/<int:project_id>/tasks")
@jwt_required()
def tasks_list(project_id: int):
    uid = current_user_id()
    ok_vis, role = require_project_visible(project_id, uid)
    if not ok_vis:
        return fail("PROJECT_FORBIDDEN", "无权限", 403)
    q = Task.query.filter_by(project_id=project_id).order_by(Task.id.desc())
    status = request.args.get("status")
    if status:
        q = q.filter(Task.status == status)
    assignee_id = request.args.get("assignee_id")
    if assignee_id:
        q = q.filter(Task.assignee_id == int(assignee_id))
    keyword = (request.args.get("q") or "").strip()
    if keyword:
        q = q.filter(Task.title.like(f"%{keyword}%"))
    page = int(request.args.get("page", "1"))
    page_size = min(int(request.args.get("page_size", "50")), 1000)
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    total = q.count()
    task_ids = [int(x.id) for x in items]
    watcher_map: dict[int, list[int]] = {}
    watched_ids = set()
    if task_ids:
        watchers = TaskWatcher.query.filter(TaskWatcher.task_id.in_(task_ids)).all()
        for w in watchers:
            tid = int(w.task_id)
            watcher_map.setdefault(tid, []).append(int(w.user_id))
        watched_ids = {tid for tid, uids in watcher_map.items() if int(uid) in set(uids)}
    return ok(
        {
            "items": [
                {
                    **to_task(x),
                    "watched_by_me": int(x.id) in watched_ids,
                    "watcher_user_ids": [int(i) for i in (watcher_map.get(int(x.id)) or [])],
                }
                for x in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
            "my_role": role,
        }
    )


@api_bp.post("/projects/<int:project_id>/tasks")
@jwt_required()
def tasks_create(project_id: int):
    uid = current_user_id()
    ok_role, role = require_project_role(project_id, uid, "user")
    if not ok_role:
        return fail("FORBIDDEN", "无权限", 403)
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "").strip()
    status = body.get("status") or "todo"
    if not title:
        return fail("VALIDATION_ERROR", "title 必填", 400)
    if not validate_workflow_status(project_id, status):
        return fail("TASK_STATUS_INVALID", "任务状态不在工作流中", 400)
    start_at = parse_iso_datetime(body.get("start_at"))
    due_at = parse_iso_datetime(body.get("due_at"))
    if body.get("start_at") and not start_at:
        return fail("VALIDATION_ERROR", "start_at 非法", 400)
    if body.get("due_at") and not due_at:
        return fail("VALIDATION_ERROR", "due_at 非法", 400)
    p0 = body.get("priority")
    if p0 is None or p0 == "":
        priority = "3"
    else:
        try:
            priority = str(int(p0))
        except Exception:
            return fail("VALIDATION_ERROR", "priority 非法", 400)
        if int(priority) < 0 or int(priority) > 5:
            return fail("VALIDATION_ERROR", "priority 非法", 400)
    t = Task(
        project_id=project_id,
        title=title,
        description_md=body.get("description_md"),
        status=status,
        priority=priority,
        assignee_id=int(body.get("assignee_id")) if body.get("assignee_id") else None,
        reporter_id=int(uid),
        start_at=start_at,
        due_at=due_at,
        completed_at=None,
    )
    db.session.add(t)
    db.session.flush()
    if not TaskWatcher.query.filter_by(task_id=int(t.id), user_id=int(uid)).first():
        db.session.add(TaskWatcher(task_id=int(t.id), user_id=int(uid)))
    if t.assignee_id and int(t.assignee_id) != int(uid):
        if not TaskWatcher.query.filter_by(task_id=int(t.id), user_id=int(t.assignee_id)).first():
            db.session.add(TaskWatcher(task_id=int(t.id), user_id=int(t.assignee_id)))
        notify(int(t.assignee_id), "task_assigned", f"你被指派了任务：{t.title}", None, f"/projects/{project_id}?tab=tasks&task={t.id}", {"task_id": int(t.id)})
    add_project_system_message(int(project_id), f"新建任务：{t.title}", int(uid))
    db.session.commit()
    return ok({"task": to_task(t), "my_role": role})


@api_bp.get("/tasks/<int:task_id>")
@jwt_required()
def tasks_get(task_id: int):
    uid = current_user_id()
    t = Task.query.get(task_id)
    if not t:
        return fail("NOT_FOUND", "任务不存在", 404)
    ok_vis, role = require_project_visible(int(t.project_id), uid)
    if not ok_vis:
        return fail("TASK_FORBIDDEN", "无权限", 403)
    attachments = TaskAttachment.query.filter_by(task_id=task_id).order_by(TaskAttachment.id.asc()).all()
    return ok({"task": to_task(t), "attachments": [{"file_id": int(x.file_id)} for x in attachments], "my_role": role})


@api_bp.patch("/tasks/<int:task_id>")
@jwt_required()
def tasks_patch(task_id: int):
    uid = current_user_id()
    t = Task.query.get(task_id)
    if not t:
        return fail("NOT_FOUND", "任务不存在", 404)
    ok_role, role = require_project_role(int(t.project_id), uid, "user")
    if not ok_role:
        return fail("TASK_FORBIDDEN", "无权限", 403)
    is_watcher = bool(TaskWatcher.query.filter_by(task_id=int(task_id), user_id=int(uid)).first())
    body = request.get_json(silent=True) or {}
    if "title" in body:
        v = (body.get("title") or "").strip()
        if v:
            t.title = v
    if "description_md" in body:
        t.description_md = body.get("description_md")
    if "status" in body:
        if not is_watcher:
            return fail("FORBIDDEN", "仅任务指定人可修改状态", 403)
        v = body.get("status")
        if not validate_workflow_status(int(t.project_id), v):
            return fail("TASK_STATUS_INVALID", "任务状态不在工作流中", 400)
        old_status = t.status
        t.status = v
        if v == "done":
            t.completed_at = utcnow()
        else:
            t.completed_at = None
        if old_status != "done" and v == "done":
            add_project_system_message(int(t.project_id), f"完成任务：{t.title}", int(uid))
    if "priority" in body:
        p0 = body.get("priority")
        if p0 is None or p0 == "":
            return fail("VALIDATION_ERROR", "priority 非法", 400)
        try:
            p = int(p0)
        except Exception:
            return fail("VALIDATION_ERROR", "priority 非法", 400)
        if p < 0 or p > 5:
            return fail("VALIDATION_ERROR", "priority 非法", 400)
        t.priority = str(p)
    if "assignee_id" in body:
        if not can_manage_project_content(role, uid):
            return fail("FORBIDDEN", "无权限指派任务", 403)
        new_assignee = int(body.get("assignee_id")) if body.get("assignee_id") else None
        if new_assignee != t.assignee_id:
            t.assignee_id = new_assignee
            if new_assignee:
                if not TaskWatcher.query.filter_by(task_id=task_id, user_id=new_assignee).first():
                    db.session.add(TaskWatcher(task_id=task_id, user_id=new_assignee))
                if int(new_assignee) != int(uid):
                    notify(int(new_assignee), "task_assigned", f"你被指派了任务：{t.title}", None, f"/projects/{t.project_id}?tab=tasks&task={t.id}", {"task_id": int(t.id)})
    if "start_at" in body:
        v = parse_iso_datetime(body.get("start_at"))
        if body.get("start_at") and not v:
            return fail("VALIDATION_ERROR", "start_at 非法", 400)
        t.start_at = v
    if "due_at" in body:
        v = parse_iso_datetime(body.get("due_at"))
        if body.get("due_at") and not v:
            return fail("VALIDATION_ERROR", "due_at 非法", 400)
        t.due_at = v
    db.session.commit()
    return ok({"task": to_task(t), "my_role": role})


@api_bp.post("/tasks/<int:task_id>/take")
@jwt_required()
def task_take(task_id: int):
    uid = current_user_id()
    t = Task.query.get(task_id)
    if not t:
        return fail("NOT_FOUND", "任务不存在", 404)
    ok_role, role = require_project_role(int(t.project_id), uid, "user")
    if not ok_role:
        return fail("TASK_FORBIDDEN", "无权限", 403)
    if not TaskWatcher.query.filter_by(task_id=int(task_id), user_id=int(uid)).first():
        db.session.add(TaskWatcher(task_id=int(task_id), user_id=int(uid)))
    db.session.commit()
    return ok({"task": to_task(t), "my_role": role})


@api_bp.post("/tasks/<int:task_id>/reject")
@jwt_required()
def task_reject(task_id: int):
    uid = current_user_id()
    t = Task.query.get(task_id)
    if not t:
        return fail("NOT_FOUND", "任务不存在", 404)
    ok_role, role = require_project_role(int(t.project_id), uid, "user")
    if not ok_role:
        return fail("TASK_FORBIDDEN", "无权限", 403)
    w = TaskWatcher.query.filter_by(task_id=int(task_id), user_id=int(uid)).first()
    if w:
        db.session.delete(w)
    if t.assignee_id and int(t.assignee_id) == int(uid):
        t.assignee_id = None
    db.session.commit()
    return ok({"task": to_task(t), "my_role": role})


@api_bp.delete("/tasks/<int:task_id>")
@jwt_required()
def tasks_delete(task_id: int):
    uid = current_user_id()
    t = Task.query.get(task_id)
    if not t:
        return fail("NOT_FOUND", "任务不存在", 404)
    ok_role, role = require_project_role(int(t.project_id), uid, "user")
    if not ok_role:
        return fail("TASK_FORBIDDEN", "无权限", 403)
    if not can_delete_owned(role, uid, int(t.reporter_id)):
        return fail("FORBIDDEN", "仅可删除自己创建的任务", 403)
    TaskWatcher.query.filter_by(task_id=task_id).delete()
    TaskAttachment.query.filter_by(task_id=task_id).delete()
    TaskComment.query.filter_by(task_id=task_id).delete()
    db.session.delete(t)
    db.session.commit()
    return ok({})


@api_bp.get("/tasks/<int:task_id>/comments")
@jwt_required()
def task_comments_list(task_id: int):
    uid = current_user_id()
    t = Task.query.get(task_id)
    if not t:
        return fail("NOT_FOUND", "任务不存在", 404)
    ok_vis, role = require_project_visible(int(t.project_id), uid)
    if not ok_vis:
        return fail("TASK_FORBIDDEN", "无权限", 403)
    items = TaskComment.query.filter_by(task_id=task_id).order_by(TaskComment.id.asc()).all()
    return ok({"items": [{"id": int(x.id), "user_id": int(x.user_id), "content_md": x.content_md, "created_at": x.created_at.isoformat()} for x in items], "my_role": role})


@api_bp.post("/tasks/<int:task_id>/comments")
@jwt_required()
def task_comments_create(task_id: int):
    uid = current_user_id()
    t = Task.query.get(task_id)
    if not t:
        return fail("NOT_FOUND", "任务不存在", 404)
    ok_role, role = require_project_role(int(t.project_id), uid, "user")
    if not ok_role:
        return fail("TASK_FORBIDDEN", "无权限", 403)
    body = request.get_json(silent=True) or {}
    content_md = body.get("content_md") or ""
    if not content_md.strip():
        return fail("VALIDATION_ERROR", "content_md 必填", 400)
    c = TaskComment(task_id=task_id, user_id=int(uid), content_md=content_md)
    db.session.add(c)
    if not TaskWatcher.query.filter_by(task_id=task_id, user_id=int(uid)).first():
        db.session.add(TaskWatcher(task_id=task_id, user_id=int(uid)))
    watchers = TaskWatcher.query.filter_by(task_id=task_id).all()
    watcher_ids = {int(x.user_id) for x in watchers}
    base_ids = set(watcher_ids)
    if t.assignee_id:
        base_ids.add(int(t.assignee_id))
    base_ids.add(int(t.reporter_id))
    mention_ids = parse_mentions(content_md)
    notify_ids = base_ids.union(mention_ids)
    notify_ids.discard(int(uid))
    for target_id in notify_ids:
        if int(target_id) in mention_ids:
            notify(int(target_id), "mention", f"你在任务评论中被提及：{t.title}", None, f"/projects/{t.project_id}?tab=tasks&task={t.id}", {"task_id": int(t.id), "comment_id": None})
        else:
            notify(int(target_id), "task_commented", f"任务有新评论：{t.title}", None, f"/projects/{t.project_id}?tab=tasks&task={t.id}", {"task_id": int(t.id)})
    db.session.commit()
    return ok({"comment": {"id": int(c.id), "user_id": int(c.user_id), "content_md": c.content_md, "created_at": c.created_at.isoformat()}, "my_role": role})


@api_bp.post("/tasks/<int:task_id>/attachments")
@jwt_required()
def task_attachment_add(task_id: int):
    uid = current_user_id()
    t = Task.query.get(task_id)
    if not t:
        return fail("NOT_FOUND", "任务不存在", 404)
    ok_role, _ = require_project_role(int(t.project_id), uid, "user")
    if not ok_role:
        return fail("FORBIDDEN", "无权限", 403)
    body = request.get_json(silent=True) or {}
    file_id = body.get("file_id")
    if not file_id:
        return fail("VALIDATION_ERROR", "file_id 必填", 400)
    if TaskAttachment.query.filter_by(task_id=task_id, file_id=int(file_id)).first():
        return ok({})
    db.session.add(TaskAttachment(task_id=task_id, file_id=int(file_id)))
    db.session.commit()
    return ok({})


@api_bp.delete("/tasks/<int:task_id>/attachments/<int:file_id>")
@jwt_required()
def task_attachment_remove(task_id: int, file_id: int):
    uid = current_user_id()
    t = Task.query.get(task_id)
    if not t:
        return fail("NOT_FOUND", "任务不存在", 404)
    ok_role, _ = require_project_role(int(t.project_id), uid, "user")
    if not ok_role:
        return fail("FORBIDDEN", "无权限", 403)
    TaskAttachment.query.filter_by(task_id=task_id, file_id=file_id).delete()
    db.session.commit()
    return ok({})


@api_bp.get("/files/root")
@jwt_required()
def files_root():
    uid = current_user_id()
    scope = request.args.get("scope")
    if scope == "personal":
        root = ensure_personal_root(int(uid))
        return ok({"root": to_file_node(root)})
    if scope == "project":
        project_id = request.args.get("project_id")
        if not project_id:
            return fail("VALIDATION_ERROR", "project_id 必填", 400)
        ok_vis, role = require_project_visible(int(project_id), uid)
        if not ok_vis:
            return fail("FILE_FORBIDDEN", "无权限", 403)
        root = ensure_project_root(int(project_id), int(uid))
        return ok({"root": to_file_node(root), "my_role": role})
    return fail("VALIDATION_ERROR", "scope 非法", 400)


@api_bp.get("/files")
@jwt_required()
def files_list():
    uid = current_user_id()
    parent_id = request.args.get("parent_id")
    if not parent_id:
        return fail("VALIDATION_ERROR", "parent_id 必填", 400)
    parent = FileNode.query.get(int(parent_id))
    if not parent or parent.deleted_at is not None:
        return fail("NOT_FOUND", "目录不存在", 404)
    if parent.type != "folder":
        return fail("FILE_NOT_A_FOLDER", "不是文件夹", 400)
    if parent.scope == "personal":
        if int(parent.owner_user_id or 0) != int(uid) and not is_super_admin(uid):
            return fail("FILE_FORBIDDEN", "无权限", 403)
    else:
        ok_vis, _ = require_project_visible(int(parent.project_id), uid)
        if not ok_vis:
            return fail("FILE_FORBIDDEN", "无权限", 403)
    items = (
        FileNode.query.filter_by(parent_id=int(parent_id), deleted_at=None)
        .order_by(FileNode.type.asc(), FileNode.id.desc())
        .all()
    )
    seen_ids = set()
    out = []
    for x in items:
        xid = int(x.id)
        if xid in seen_ids:
            continue
        seen_ids.add(xid)
        out.append(to_file_node(x))
    return ok({"items": out})


@api_bp.post("/files/folders")
@jwt_required()
def files_create_folder():
    uid = current_user_id()
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    parent_id = body.get("parent_id")
    scope = body.get("scope")
    project_id = body.get("project_id")
    if not name or not parent_id or not scope:
        return fail("VALIDATION_ERROR", "name/parent_id/scope 必填", 400)
    parent = FileNode.query.get(int(parent_id))
    if not parent or parent.deleted_at is not None or parent.type != "folder":
        return fail("NOT_FOUND", "父目录不存在", 404)
    if scope != parent.scope:
        return fail("VALIDATION_ERROR", "scope 与父目录不一致", 400)
    if scope == "personal":
        if int(parent.owner_user_id or 0) != int(uid) and not is_super_admin(uid):
            return fail("FILE_FORBIDDEN", "无权限", 403)
        node = create_folder(name, int(parent_id), "personal", int(uid), None, int(uid))
    else:
        if not project_id or int(project_id) != int(parent.project_id):
            return fail("VALIDATION_ERROR", "project_id 非法", 400)
        ok_role, _ = require_project_role(int(project_id), uid, "user")
        if not ok_role:
            return fail("FILE_FORBIDDEN", "无权限", 403)
        node = create_folder(name, int(parent_id), "project", None, int(project_id), int(uid))
        add_project_system_message(int(project_id), f"新建文件夹：{name}", int(uid))
    db.session.commit()
    return ok({"folder": to_file_node(node)})


UPLOAD_CHUNK_BYTES_DEFAULT = 8 * 1024 * 1024
UPLOAD_CHUNK_BYTES_MAX = 32 * 1024 * 1024


def upload_tmp_root(project_id=None):
    root = legacy_storage_root()
    path = os.path.join(root, "uploads")
    os.makedirs(path, exist_ok=True)
    return path


def safe_upload_id(upload_id: str):
    value = (upload_id or "").strip()
    if not value or any(ch not in "0123456789abcdef-" for ch in value):
        return None
    return value


def upload_session_dir(upload_id: str, project_id=None):
    clean = safe_upload_id(upload_id)
    if not clean:
        return None
    # Existing sessions keep their location, including those started before migration.
    roots = [legacy_storage_root(), dc_storage_root()]
    for root in dict.fromkeys(roots):
        path = os.path.realpath(os.path.join(root, "uploads", clean))
        uploads = os.path.realpath(os.path.join(root, "uploads"))
        if os.path.commonpath([uploads, path]) != uploads:
            return None
        if os.path.isdir(path):
            return path
    return os.path.join(upload_tmp_root(project_id), clean)


def upload_meta_path(upload_id: str):
    path = upload_session_dir(upload_id)
    return os.path.join(path, "meta.json") if path else None


def save_upload_meta(upload_id: str, meta: dict):
    path = upload_session_dir(upload_id, meta.get("project_id"))
    if not path:
        raise ValueError("invalid upload id")
    os.makedirs(path, exist_ok=True)
    tmp_path = os.path.join(path, "meta.json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp_path, os.path.join(path, "meta.json"))


def load_upload_meta(upload_id: str):
    path = upload_meta_path(upload_id)
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_upload_parent(scope: str, parent_id, project_id, uid: int):
    if not scope or not parent_id:
        return None, fail("VALIDATION_ERROR", "scope/parent_id 必填", 400)
    parent = FileNode.query.get(int(parent_id))
    if not parent or parent.deleted_at is not None or parent.type != "folder":
        return None, fail("NOT_FOUND", "父目录不存在", 404)
    if parent.scope != scope:
        return None, fail("VALIDATION_ERROR", "scope 与父目录不一致", 400)
    if scope == "personal":
        if int(parent.owner_user_id or 0) != int(uid) and not is_super_admin(uid):
            return None, fail("FILE_FORBIDDEN", "无权限", 403)
        return parent, None
    if scope != "project":
        return None, fail("VALIDATION_ERROR", "scope 非法", 400)
    if not project_id or int(project_id) != int(parent.project_id):
        return None, fail("VALIDATION_ERROR", "project_id 非法", 400)
    ok_role, _ = require_project_role(int(project_id), uid, "user")
    if not ok_role:
        return None, fail("FILE_FORBIDDEN", "无权限", 403)
    return parent, None


def upload_session_response(meta: dict):
    chunks = meta.get("chunks") or {}
    uploaded_bytes = sum(int(x.get("size") or 0) for x in chunks.values())
    size = int(meta.get("size") or 0)
    return {
        "upload_id": meta.get("upload_id"),
        "filename": meta.get("filename"),
        "size": size,
        "chunk_size": int(meta.get("chunk_size") or UPLOAD_CHUNK_BYTES_DEFAULT),
        "uploaded_chunks": sorted(int(k) for k in chunks.keys()),
        "uploaded_bytes": min(uploaded_bytes, size),
        "percent": round((min(uploaded_bytes, size) / size) * 100, 2) if size else 0,
    }


def authorize_file_node(node: FileNode, uid: int):
    if node.scope == "personal":
        return int(node.owner_user_id or 0) == int(uid) or is_super_admin(uid)
    ok_vis, _ = require_project_visible(int(node.project_id), uid)
    return ok_vis


def authorize_folder_node(node: FileNode, uid: int):
    if not node or node.deleted_at is not None or node.type != "folder":
        return False
    if node.scope == "personal":
        return int(node.owner_user_id or 0) == int(uid) or is_super_admin(uid)
    ok_vis, _ = require_project_visible(int(node.project_id), uid)
    return ok_vis


def resolve_file_content(file_id: int, uid: int):
    node = FileNode.query.get(file_id)
    if not node or node.deleted_at is not None or node.type != "file":
        return None, None, None, fail("NOT_FOUND", "文件不存在", 404)
    if not authorize_file_node(node, uid):
        return None, None, None, fail("FILE_FORBIDDEN", "无权限", 403)
    so = StorageObject.query.get(int(node.storage_object_id))
    if not so:
        return None, None, None, fail("NOT_FOUND", "内容实体不存在", 404)
    try:
        abs_path = resolve_object_path(so.storage_rel_path)
    except ValueError:
        return None, None, None, fail("FILE_FORBIDDEN", "无权限", 403)
    return node, so, abs_path, None


def find_soffice_bin():
    configured = current_app.config.get("SOFFICE_BIN")
    candidates = [
        configured,
        "soffice",
        "libreoffice",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if os.path.isabs(candidate) and os.path.exists(candidate):
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None


def file_ext(name: str):
    return os.path.splitext(name or "")[1].lower().lstrip(".")


OFFICE_PREVIEW_EXTS = {
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "odt",
    "ods",
    "odp",
    "rtf",
}


def office_preview_cache_path(node: FileNode, so: StorageObject):
    cache_dir = os.path.join(legacy_storage_root(), "preview_cache")
    os.makedirs(cache_dir, exist_ok=True)
    key = f"{int(node.id)}_{int(so.id)}_{int(so.size_bytes or 0)}_{int(node.updated_at.timestamp())}"
    return os.path.join(cache_dir, f"{key}.pdf")


def convert_office_to_pdf(src_path: str, original_name: str, target_path: str):
    soffice = find_soffice_bin()
    if not soffice:
        return fail("PREVIEW_CONVERTER_MISSING", "服务器未安装 LibreOffice，无法预览 Office 文件", 501)
    with tempfile.TemporaryDirectory() as tmpdir:
        safe_name = os.path.basename(original_name or f"preview.{file_ext(src_path)}")
        work_src = os.path.join(tmpdir, safe_name)
        profile_dir = os.path.join(tmpdir, "lo_profile")
        os.makedirs(profile_dir, exist_ok=True)
        shutil.copyfile(src_path, work_src)
        env = os.environ.copy()
        env["HOME"] = tmpdir
        env["TMPDIR"] = tmpdir
        env["TEMP"] = tmpdir
        env["TMP"] = tmpdir
        result = subprocess.run(
            [
                soffice,
                "--headless",
                "--nologo",
                "--nofirststartwizard",
                "--norestore",
                f"-env:UserInstallation=file:///{profile_dir.replace(os.sep, '/')}",
                "--convert-to",
                "pdf",
                "--outdir",
                tmpdir,
                work_src,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            check=False,
            env=env,
        )
        converted = os.path.join(tmpdir, f"{os.path.splitext(os.path.basename(work_src))[0]}.pdf")
        if not os.path.exists(converted):
            pdfs = [
                os.path.join(tmpdir, x)
                for x in os.listdir(tmpdir)
                if x.lower().endswith(".pdf") and os.path.isfile(os.path.join(tmpdir, x))
            ]
            converted = pdfs[0] if pdfs else converted
        if result.returncode != 0 or not os.path.exists(converted):
            detail = "\n".join([result.stdout or "", result.stderr or ""]).strip()
            if len(detail) > 500:
                detail = detail[:500]
            return fail("PREVIEW_CONVERT_FAILED", f"Office 文件转换预览失败：{detail or '未生成 PDF'}", 500)
        # Concurrent readers only see a complete PDF. Replacing the cache name
        # also leaves an already-open response attached to its original inode.
        descriptor, pending = tempfile.mkstemp(prefix=".preview-", suffix=".tmp", dir=os.path.dirname(target_path))
        os.close(descriptor)
        try:
            shutil.copyfile(converted, pending)
            os.replace(pending, target_path)
        finally:
            if os.path.exists(pending):
                os.unlink(pending)
    return None


def safe_zip_part(name: str):
    value = (name or "unnamed").replace("\\", "/").split("/")[-1].strip()
    return value or "unnamed"


def unique_zip_name(path: str, used: set[str]):
    if path not in used:
        used.add(path)
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while True:
        candidate = f"{base} ({i}){ext}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        i += 1


def set_zip_task(task_id: str, **patch):
    with ZIP_TASK_LOCK:
        current = ZIP_TASKS.get(task_id, {})
        current.update(patch)
        current["updated_at"] = time.time()
        ZIP_TASKS[task_id] = current


def get_zip_task(task_id: str):
    with ZIP_TASK_LOCK:
        task = ZIP_TASKS.get(task_id)
        return dict(task) if task else None


def public_zip_task(task_id: str):
    task = get_zip_task(task_id) or {}
    return {
        "id": task.get("id") or task_id,
        "folder_id": task.get("folder_id"),
        "status": task.get("status") or "unknown",
        "message": task.get("message") or "",
        "percent": int(task.get("percent") or 0),
        "total": int(task.get("total") or 0),
        "done": int(task.get("done") or 0),
        "filename": task.get("filename") or "folder.zip",
    }


def collect_folder_zip_entries(folder_id: int, base_path: str = ""):
    entries = []
    children = (
        FileNode.query.filter_by(parent_id=int(folder_id), deleted_at=None)
        .order_by(FileNode.type.asc(), FileNode.name.asc(), FileNode.id.asc())
        .all()
    )
    for child in children:
        name = safe_zip_part(child.name)
        rel_path = f"{base_path}/{name}" if base_path else name
        if child.type == "folder":
            entries.append({"type": "folder", "path": rel_path})
            entries.extend(collect_folder_zip_entries(int(child.id), rel_path))
            continue
        if child.type != "file" or not child.storage_object_id:
            continue
        so = StorageObject.query.get(int(child.storage_object_id))
        if not so:
            continue
        entries.append({"type": "file", "path": rel_path, "storage_rel_path": so.storage_rel_path})
    return entries


def build_folder_zip_task(app, task_id: str, folder_id: int, folder_name: str):
    with app.app_context():
        try:
            set_zip_task(task_id, status="running", message="正在扫描文件夹", percent=2)
            entries = collect_folder_zip_entries(int(folder_id))
            file_entries = [x for x in entries if x["type"] == "file"]
            total = len(file_entries)
            folder = db.session.get(FileNode, int(folder_id))
            cache_dir = os.path.join(legacy_storage_root(), "zip_tasks")
            os.makedirs(cache_dir, exist_ok=True)
            zip_path = os.path.join(cache_dir, f"{task_id}.zip")
            used = set()
            set_zip_task(task_id, status="running", message="正在打包", total=total, done=0, percent=5)
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                for entry in entries:
                    arcname = unique_zip_name(entry["path"].replace("\\", "/").strip("/"), used)
                    if not arcname:
                        continue
                    if entry["type"] == "folder":
                        zf.writestr(f"{arcname}/", "")
                        continue
                    abs_path = resolve_object_path(entry["storage_rel_path"])
                    if not os.path.isfile(abs_path):
                        raise FileNotFoundError("A source file is unavailable")
                    zf.write(abs_path, arcname)
                    done = int(get_zip_task(task_id).get("done", 0)) + 1
                    percent = 5 + int((done / max(total, 1)) * 90)
                    set_zip_task(task_id, done=done, percent=min(percent, 95))
            filename = f"{safe_zip_part(folder_name)}.zip"
            set_zip_task(task_id, status="done", message="打包完成", percent=100, path=zip_path, filename=filename)
        except Exception as exc:
            set_zip_task(task_id, status="error", message=f"打包失败：{exc}", percent=0)


def require_upload_session(upload_id: str, uid: int):
    meta = load_upload_meta(upload_id)
    if not meta:
        return None, fail("NOT_FOUND", "上传会话不存在", 404)
    if int(meta.get("created_by") or 0) != int(uid) and not is_super_admin(uid):
        return None, fail("FILE_FORBIDDEN", "无权限", 403)
    _, err = validate_upload_parent(
        meta.get("scope"),
        meta.get("parent_id"),
        meta.get("project_id"),
        uid,
    )
    if err:
        return None, err
    return meta, None


@api_bp.post("/files/upload-sessions")
@jwt_required()
def files_create_upload_session():
    uid = current_user_id()
    body = request.get_json(silent=True) or {}
    filename = (body.get("filename") or "").strip() or "unnamed"
    scope = body.get("scope")
    parent_id = body.get("parent_id")
    project_id = body.get("project_id")
    size = int(body.get("size") or 0)
    chunk_size = int(body.get("chunk_size") or UPLOAD_CHUNK_BYTES_DEFAULT)
    if size <= 0:
        return fail("VALIDATION_ERROR", "size 必须大于 0", 400)
    max_bytes = int(current_app.config["MAX_UPLOAD_MB"]) * 1024 * 1024
    if size > max_bytes:
        return fail("FILE_TOO_LARGE", "文件过大", 413)
    if chunk_size <= 0:
        chunk_size = UPLOAD_CHUNK_BYTES_DEFAULT
    chunk_size = min(chunk_size, UPLOAD_CHUNK_BYTES_MAX)
    parent, err = validate_upload_parent(scope, parent_id, project_id, uid)
    if err:
        return err
    upload_id = uuid.uuid4().hex
    meta = {
        "upload_id": upload_id,
        "filename": filename,
        "size": size,
        "chunk_size": chunk_size,
        "scope": scope,
        "parent_id": int(parent.id),
        "project_id": int(project_id) if scope == "project" and project_id else None,
        "owner_user_id": int(uid) if scope == "personal" else None,
        "mime_type": (body.get("mime_type") or None),
        "created_by": int(uid),
        "chunks": {},
    }
    save_upload_meta(upload_id, meta)
    return ok({"session": upload_session_response(meta)})


@api_bp.get("/files/upload-sessions/<upload_id>")
@jwt_required()
def files_get_upload_session(upload_id: str):
    uid = current_user_id()
    meta, err = require_upload_session(upload_id, uid)
    if err:
        return err
    return ok({"session": upload_session_response(meta)})


@api_bp.put("/files/upload-sessions/<upload_id>/chunks/<int:index>")
@jwt_required()
def files_upload_chunk(upload_id: str, index: int):
    uid = current_user_id()
    meta, err = require_upload_session(upload_id, uid)
    if err:
        return err
    if index < 0:
        return fail("VALIDATION_ERROR", "chunk index 非法", 400)
    size = int(meta.get("size") or 0)
    chunk_size = int(meta.get("chunk_size") or UPLOAD_CHUNK_BYTES_DEFAULT)
    offset = index * chunk_size
    if offset >= size:
        return fail("VALIDATION_ERROR", "chunk index 超出范围", 400)
    expected_size = min(chunk_size, size - offset)
    content_length = request.content_length
    if content_length is not None and content_length > expected_size:
        return fail("VALIDATION_ERROR", "chunk size 超出范围", 400)
    session_path = upload_session_dir(upload_id)
    if not session_path:
        return fail("VALIDATION_ERROR", "upload_id 非法", 400)
    os.makedirs(session_path, exist_ok=True)
    part_path = os.path.join(session_path, f"{index}.part")
    tmp_path = part_path + ".tmp"
    received = 0
    with open(tmp_path, "wb") as out:
        while True:
            chunk = request.stream.read(1024 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > expected_size:
                out.close()
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                return fail("VALIDATION_ERROR", "chunk size 超出范围", 400)
            out.write(chunk)
    if received != expected_size:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return fail("VALIDATION_ERROR", "chunk size 不完整", 400)
    os.replace(tmp_path, part_path)
    meta.setdefault("chunks", {})[str(index)] = {"size": received}
    save_upload_meta(upload_id, meta)
    return ok({"session": upload_session_response(meta)})


@api_bp.post("/files/upload-sessions/<upload_id>/complete")
@jwt_required()
def files_complete_upload_session(upload_id: str):
    uid = current_user_id()
    meta, err = require_upload_session(upload_id, uid)
    if err:
        return err
    size = int(meta.get("size") or 0)
    chunk_size = int(meta.get("chunk_size") or UPLOAD_CHUNK_BYTES_DEFAULT)
    total_chunks = (size + chunk_size - 1) // chunk_size
    chunks = meta.get("chunks") or {}
    missing = [i for i in range(total_chunks) if str(i) not in chunks]
    if missing:
        return fail("UPLOAD_INCOMPLETE", "分片尚未全部上传", 400)
    session_path = upload_session_dir(upload_id)
    rel_path = new_object_rel_path(meta.get("project_id") if meta.get("scope") == "project" else None)
    abs_path = resolve_object_path(rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    written = 0
    try:
        with open(abs_path, "wb") as out:
            for i in range(total_chunks):
                part_path = os.path.join(session_path, f"{i}.part")
                if not os.path.exists(part_path):
                    raise FileNotFoundError(part_path)
                with open(part_path, "rb") as part:
                    shutil.copyfileobj(part, out)
                written += os.path.getsize(part_path)
        if written != size:
            raise ValueError("merged size mismatch")
    except Exception:
        try:
            if os.path.exists(abs_path):
                os.remove(abs_path)
        except OSError:
            pass
        return fail("UPLOAD_MERGE_FAILED", "合并分片失败", 500)

    so = StorageObject(
        mime_type=meta.get("mime_type"),
        size_bytes=size,
        storage_rel_path=rel_path.replace("\\", "/"),
        sha256=None,
        created_by=int(uid),
    )
    db.session.add(so)
    db.session.flush()
    if meta.get("scope") == "personal":
        node = create_file_node(
            meta.get("filename") or "unnamed",
            int(meta.get("parent_id")),
            "personal",
            int(uid),
            None,
            int(so.id),
            int(uid),
        )
    else:
        project_id = int(meta.get("project_id"))
        node = create_file_node(
            meta.get("filename") or "unnamed",
            int(meta.get("parent_id")),
            "project",
            None,
            project_id,
            int(so.id),
            int(uid),
        )
        add_project_system_message(project_id, f"上传文件：{meta.get('filename') or 'unnamed'}", int(uid))
    db.session.commit()
    try:
        shutil.rmtree(session_path)
    except OSError:
        pass
    return ok({"file": to_file_node(node)})


@api_bp.delete("/files/upload-sessions/<upload_id>")
@jwt_required()
def files_cancel_upload_session(upload_id: str):
    uid = current_user_id()
    meta, err = require_upload_session(upload_id, uid)
    if err:
        return err
    path = upload_session_dir(upload_id)
    if path and os.path.exists(path):
        shutil.rmtree(path)
    return ok({})


@api_bp.post("/files/upload")
@jwt_required()
def files_upload():
    uid = current_user_id()
    scope = request.form.get("scope")
    parent_id = request.form.get("parent_id")
    project_id = request.form.get("project_id")
    if not scope or not parent_id:
        return fail("VALIDATION_ERROR", "scope/parent_id 必填", 400)
    parent = FileNode.query.get(int(parent_id))
    if not parent or parent.deleted_at is not None or parent.type != "folder":
        return fail("NOT_FOUND", "父目录不存在", 404)
    if parent.scope != scope:
        return fail("VALIDATION_ERROR", "scope 与父目录不一致", 400)
    f = request.files.get("file")
    if not f:
        return fail("VALIDATION_ERROR", "file 必填", 400)
    max_bytes = int(current_app.config["MAX_UPLOAD_MB"]) * 1024 * 1024
    if request.content_length and request.content_length > max_bytes:
        return fail("FILE_TOO_LARGE", "文件过大", 413)
    filename = (getattr(f, "filename", "") or "").strip() or "unnamed"
    if scope == "personal":
        if int(parent.owner_user_id or 0) != int(uid) and not is_super_admin(uid):
            return fail("FILE_FORBIDDEN", "无权限", 403)
        so = create_storage_object(f, int(uid))
        node = create_file_node(filename, int(parent_id), "personal", int(uid), None, int(so.id), int(uid))
    else:
        if not project_id or int(project_id) != int(parent.project_id):
            return fail("VALIDATION_ERROR", "project_id 非法", 400)
        ok_role, _ = require_project_role(int(project_id), uid, "user")
        if not ok_role:
            return fail("FILE_FORBIDDEN", "无权限", 403)
        so = create_storage_object(f, int(uid), project_id=int(project_id))
        node = create_file_node(filename, int(parent_id), "project", None, int(project_id), int(so.id), int(uid))
        add_project_system_message(int(project_id), f"上传文件：{filename}", int(uid))
    db.session.commit()
    return ok({"file": to_file_node(node)})


@api_bp.post("/files/link")
@jwt_required()
def files_link():
    uid = current_user_id()
    body = request.get_json(silent=True) or {}
    source_file_id = body.get("source_file_id")
    target_parent_id = body.get("target_parent_id")
    target_scope = body.get("target_scope")
    target_project_id = body.get("target_project_id")
    target_owner_user_id = body.get("target_owner_user_id")
    if not source_file_id or not target_parent_id or not target_scope:
        return fail("VALIDATION_ERROR", "source_file_id/target_parent_id/target_scope 必填", 400)
    src = FileNode.query.get(int(source_file_id))
    if not src or src.deleted_at is not None or src.type != "file":
        return fail("NOT_FOUND", "源文件不存在", 404)
    if src.scope == "personal":
        if int(src.owner_user_id or 0) != int(uid) and not is_super_admin(uid):
            return fail("FILE_FORBIDDEN", "无权限", 403)
    else:
        ok_vis, _ = require_project_visible(int(src.project_id), uid)
        if not ok_vis:
            return fail("FILE_FORBIDDEN", "无权限", 403)
    parent = FileNode.query.get(int(target_parent_id))
    if not parent or parent.deleted_at is not None or parent.type != "folder":
        return fail("NOT_FOUND", "目标目录不存在", 404)
    if parent.scope != target_scope:
        return fail("VALIDATION_ERROR", "target_scope 与目标目录不一致", 400)
    if target_scope == "personal":
        if int(target_owner_user_id or 0) != int(uid) and not is_super_admin(uid):
            return fail("FILE_FORBIDDEN", "无权限写入个人空间", 403)
        if int(parent.owner_user_id or 0) != int(target_owner_user_id or 0):
            return fail("VALIDATION_ERROR", "目标目录不属于该用户", 400)
        source_object = db.session.get(StorageObject, int(src.storage_object_id))
        if not source_object:
            return fail("NOT_FOUND", "内容实体不存在", 404)
        target_object = object_for_project(source_object)
        node = create_file_node(src.name, int(target_parent_id), "personal", int(target_owner_user_id), None, int(target_object.id), int(uid))
    else:
        if not target_project_id or int(parent.project_id or 0) != int(target_project_id):
            return fail("VALIDATION_ERROR", "target_project_id 非法", 400)
        ok_role, _ = require_project_role(int(target_project_id), uid, "user")
        if not ok_role:
            return fail("FILE_FORBIDDEN", "无权限写入项目空间", 403)
        source_object = db.session.get(StorageObject, int(src.storage_object_id))
        if not source_object:
            return fail("NOT_FOUND", "内容实体不存在", 404)
        target_object = object_for_project(source_object, int(target_project_id))
        node = create_file_node(src.name, int(target_parent_id), "project", None, int(target_project_id), int(target_object.id), int(uid))
    db.session.commit()
    return ok({"file": to_file_node(node)})


@api_bp.post("/files/<int:file_id>/replace")
@jwt_required()
def files_replace(file_id: int):
    uid = current_user_id()
    node = FileNode.query.get(file_id)
    if not node or node.deleted_at is not None or node.type != "file":
        return fail("NOT_FOUND", "文件不存在", 404)
    if node.scope == "personal":
        if int(node.owner_user_id or 0) != int(uid) and not is_super_admin(uid):
            return fail("FILE_FORBIDDEN", "无权限", 403)
    else:
        ok_role, _ = require_project_role(int(node.project_id), uid, "user")
        if not ok_role:
            return fail("FILE_FORBIDDEN", "无权限", 403)
    f = request.files.get("file")
    if not f:
        return fail("VALIDATION_ERROR", "file 必填", 400)
    max_bytes = int(current_app.config["MAX_UPLOAD_MB"]) * 1024 * 1024
    if request.content_length and request.content_length > max_bytes:
        return fail("FILE_TOO_LARGE", "文件过大", 413)
    so = StorageObject.query.get(int(node.storage_object_id))
    if not so:
        return fail("NOT_FOUND", "内容实体不存在", 404)
    old_rel = so.storage_rel_path
    new_so = create_storage_object(f, int(uid), project_id=node.project_id if node.scope == "project" else None)
    references = FileNode.query.filter_by(storage_object_id=int(so.id)).all()
    same_destination = [ref for ref in references if path_matches_project(
        new_so.storage_rel_path, ref.project_id if ref.scope == "project" else None
    )]
    keep_original = len(same_destination) != len(references)
    if keep_original:
        # Legacy links can span both roots before migration; split only this destination.
        for ref in same_destination:
            ref.storage_object_id = int(new_so.id)
    else:
        # Release the temporary row's unique path before assigning it to the old row.
        mime_type, size_bytes, new_rel = new_so.mime_type, new_so.size_bytes, new_so.storage_rel_path
        db.session.delete(new_so)
        db.session.flush()
        so.mime_type = mime_type
        so.size_bytes = size_bytes
        so.storage_rel_path = new_rel
        so.sha256 = None
        so.updated_at = utcnow()
    if node.scope == "project" and node.project_id:
        add_project_system_message(int(node.project_id), f"更新文件内容：{node.name}", int(uid))
    db.session.commit()
    try:
        abs_old = resolve_object_path(old_rel)
        if not keep_original and old_rel != so.storage_rel_path and os.path.exists(abs_old):
            os.remove(abs_old)
    except Exception:
        pass
    return ok({})


@api_bp.get("/files/<int:file_id>/download")
@jwt_required()
def files_download(file_id: int):
    uid = current_user_id()
    node, _, abs_path, err = resolve_file_content(file_id, uid)
    if err:
        return err
    return send_file(abs_path, as_attachment=True, download_name=node.name)


@api_bp.post("/files/<int:folder_id>/zip-tasks")
@jwt_required()
def files_create_zip_task(folder_id: int):
    uid = current_user_id()
    folder = FileNode.query.get(folder_id)
    if not authorize_folder_node(folder, uid):
        return fail("NOT_FOUND", "文件夹不存在或无权限", 404)
    task_id = uuid.uuid4().hex
    set_zip_task(
        task_id,
        id=task_id,
        folder_id=int(folder.id),
        owner_user_id=int(uid),
        status="queued",
        message="等待打包",
        percent=0,
        total=0,
        done=0,
        filename=f"{safe_zip_part(folder.name)}.zip",
    )
    app = current_app._get_current_object()
    t = threading.Thread(
        target=build_folder_zip_task,
        args=(app, task_id, int(folder.id), folder.name),
        daemon=True,
    )
    t.start()
    return ok({"task": public_zip_task(task_id)})


@api_bp.get("/files/zip-tasks/<task_id>")
@jwt_required()
def files_get_zip_task(task_id: str):
    uid = current_user_id()
    task = get_zip_task(task_id)
    if not task or int(task.get("owner_user_id") or 0) != int(uid):
        return fail("NOT_FOUND", "打包任务不存在", 404)
    return ok({"task": public_zip_task(task_id)})


@api_bp.get("/files/zip-tasks/<task_id>/download")
@jwt_required()
def files_download_zip_task(task_id: str):
    uid = current_user_id()
    task = get_zip_task(task_id)
    if not task or int(task.get("owner_user_id") or 0) != int(uid):
        return fail("NOT_FOUND", "打包任务不存在", 404)
    if task.get("status") != "done" or not task.get("path") or not os.path.exists(task.get("path")):
        return fail("ZIP_NOT_READY", "压缩包尚未生成完成", 409)
    return send_file(task["path"], as_attachment=True, download_name=task.get("filename") or "folder.zip")


@api_bp.get("/files/<int:file_id>/preview")
def files_preview(file_id: int):
    authorization = (request.headers.get("Authorization") or "").strip()
    if authorization:
        pieces = authorization.split()
        token = pieces[1] if len(pieces) == 2 and pieces[0].lower() == "bearer" else ""
    else:
        token = (request.args.get("token") or "").strip()
    if not token:
        return fail("UNAUTHORIZED", "未登录", 401)
    try:
        from .auth_sessions import validate_access_claims
        payload = decode_token(token)
        if not validate_access_claims(payload):
            return fail("UNAUTHORIZED", "登录已失效", 401)
        uid = int(payload.get("sub"))
    except Exception:
        return fail("UNAUTHORIZED", "登录已失效", 401)
    node, so, abs_path, err = resolve_file_content(file_id, uid)
    if err:
        return err
    ext = file_ext(node.name)
    if ext in OFFICE_PREVIEW_EXTS:
        target_path = office_preview_cache_path(node, so)
        if not os.path.exists(target_path):
            convert_err = convert_office_to_pdf(abs_path, node.name, target_path)
            if convert_err:
                return convert_err
        # Conversion may take a minute; authorize again using a fresh database
        # snapshot before releasing the resulting private document.
        previous_object_id = int(so.id)
        db.session.rollback()
        if not validate_access_claims(payload):
            return fail("UNAUTHORIZED", "登录已失效", 401)
        node, so, _, err = resolve_file_content(file_id, uid)
        if err:
            return err
        if int(so.id) != previous_object_id:
            return fail("PREVIEW_CHANGED", "文件已更新，请重新打开预览", 409)
        return send_file(
            target_path,
            mimetype="application/pdf",
            as_attachment=False,
            download_name=f"{os.path.splitext(node.name)[0]}.pdf",
            conditional=True,
        )
    return send_file(
        abs_path,
        mimetype=so.mime_type or "application/octet-stream",
        as_attachment=False,
        download_name=node.name,
        conditional=True,
    )


@api_bp.patch("/files/<int:file_id>")
@jwt_required()
def files_patch(file_id: int):
    uid = current_user_id()
    node = FileNode.query.get(file_id)
    if not node or node.deleted_at is not None:
        return fail("NOT_FOUND", "节点不存在", 404)
    old_name = node.name
    old_parent_id = int(node.parent_id) if node.parent_id else None
    if node.scope == "personal":
        if int(node.owner_user_id or 0) != int(uid) and not is_super_admin(uid):
            return fail("FILE_FORBIDDEN", "无权限", 403)
    else:
        ok_role, _ = require_project_role(int(node.project_id), uid, "user")
        if not ok_role:
            return fail("FILE_FORBIDDEN", "无权限", 403)
    body = request.get_json(silent=True) or {}
    if "name" in body:
        v = (body.get("name") or "").strip()
        if v:
            node.name = v
    if "parent_id" in body:
        pid = body.get("parent_id")
        parent = FileNode.query.get(int(pid)) if pid else None
        if not parent or parent.deleted_at is not None or parent.type != "folder":
            return fail("NOT_FOUND", "目标目录不存在", 404)
        if node.type == "folder":
            if int(parent.id) == int(node.id):
                return fail("VALIDATION_ERROR", "不能移动到自身目录", 400)
            cursor = parent
            while cursor.parent_id:
                if int(cursor.parent_id) == int(node.id):
                    return fail("VALIDATION_ERROR", "不能移动到子目录", 400)
                cursor = FileNode.query.get(int(cursor.parent_id))
                if not cursor or cursor.deleted_at is not None:
                    break
        if parent.scope != node.scope:
            return fail("VALIDATION_ERROR", "scope 不一致", 400)
        if node.scope == "personal" and int(parent.owner_user_id or 0) != int(node.owner_user_id or 0):
            return fail("VALIDATION_ERROR", "目标目录不属于该用户", 400)
        if node.scope == "project" and int(parent.project_id or 0) != int(node.project_id or 0):
            return fail("VALIDATION_ERROR", "目标目录不属于该项目", 400)
        node.parent_id = int(pid)
    if node.scope == "project" and node.project_id:
        changed = []
        if node.name != old_name:
            changed.append(f"重命名：{old_name} -> {node.name}")
        new_parent_id = int(node.parent_id) if node.parent_id else None
        if new_parent_id != old_parent_id:
            changed.append("移动位置")
        if changed:
            add_project_system_message(int(node.project_id), f"修改文件：{'; '.join(changed)}", int(uid))
    db.session.commit()
    return ok({"node": to_file_node(node)})


@api_bp.delete("/files/<int:file_id>")
@jwt_required()
def files_delete(file_id: int):
    uid = current_user_id()
    node = FileNode.query.get(file_id)
    if not node or node.deleted_at is not None:
        return fail("NOT_FOUND", "节点不存在", 404)
    if node.scope == "personal":
        if int(node.owner_user_id or 0) != int(uid) and not is_super_admin(uid):
            return fail("FILE_FORBIDDEN", "无权限", 403)
        allow = True
        role = "creator"
    else:
        ok_role, role = require_project_role(int(node.project_id), uid, "user")
        if not ok_role:
            return fail("FILE_FORBIDDEN", "无权限", 403)
        allow = can_delete_owned(role, uid, int(node.created_by))
    if not allow:
        return fail("FORBIDDEN", "仅可删除自己上传的文件", 403)
    descendants = [node]
    if node.type == "folder":
        pending = [int(node.id)]
        seen = {int(node.id)}
        while pending:
            children = FileNode.query.filter(FileNode.parent_id.in_(pending), FileNode.deleted_at.is_(None), FileNode.scope == node.scope).all()
            children = [child for child in children if child.project_id == node.project_id and child.owner_user_id == node.owner_user_id and int(child.id) not in seen]
            if node.scope == "project" and any(not can_delete_owned(role, uid, int(child.created_by)) for child in children):
                return fail("FORBIDDEN", "文件夹中包含无权删除的文件", 403)
            pending = [int(child.id) for child in children]
            seen.update(pending)
            descendants.extend(children)
    deleted_at = utcnow()
    object_ids = {int(child.storage_object_id) for child in descendants if child.storage_object_id}
    for child in descendants:
        child.deleted_at = deleted_at
    if node.scope == "project" and node.project_id:
        add_project_system_message(int(node.project_id), f"删除{('文件夹' if node.type == 'folder' else '文件')}：{node.name}", int(uid))
    db.session.commit()
    for object_id in object_ids:
        still_ref = (
            FileNode.query.filter(
                FileNode.storage_object_id == object_id,
                FileNode.deleted_at.is_(None),
            )
            .count()
            > 0
        )
        if not still_ref:
            so = StorageObject.query.get(object_id)
            if so:
                abs_path = resolve_object_path(so.storage_rel_path)
                readable_managed = (
                    current_app.extensions.get("readable_storage")
                    and current_app.config.get("READABLE_STORAGE_ENABLED", True)
                    and so.storage_rel_path.startswith(DC_PREFIX)
                )
                db.session.delete(so)
                db.session.commit()
                try:
                    if not readable_managed and os.path.exists(abs_path):
                        os.remove(abs_path)
                except Exception:
                    pass
    return ok({})


@api_bp.get("/calendar/events")
@jwt_required()
def calendar_events_list():
    uid = current_user_id()
    scope = request.args.get("scope") or "personal"
    from_s = request.args.get("from")
    to_s = request.args.get("to")
    from_dt = parse_iso_datetime(from_s) if from_s else None
    to_dt = parse_iso_datetime(to_s) if to_s else None
    q = CalendarEvent.query
    if scope == "personal":
        q = q.filter(CalendarEvent.scope == "personal", CalendarEvent.owner_user_id == int(uid))
    elif scope == "mine":
        project_ids = db.session.query(ProjectMember.project_id).filter_by(user_id=int(uid)).union(db.session.query(Project.id).filter_by(creator_id=int(uid)))
        if is_super_admin(uid):
            project_ids = db.session.query(Project.id)
        q = q.filter(or_(
            (CalendarEvent.scope == "personal") & (CalendarEvent.owner_user_id == int(uid)),
            (CalendarEvent.scope == "project") & (CalendarEvent.assignee_id == int(uid)) & CalendarEvent.project_id.in_(project_ids),
        ))
    elif scope == "project":
        project_id = request.args.get("project_id")
        if not project_id:
            return fail("VALIDATION_ERROR", "project_id 必填", 400)
        ok_vis, _ = require_project_visible(int(project_id), uid)
        if not ok_vis:
            return fail("FORBIDDEN", "无权限", 403)
        q = q.filter(CalendarEvent.scope == "project", CalendarEvent.project_id == int(project_id))
    else:
        return fail("VALIDATION_ERROR", "scope 非法", 400)
    if from_dt:
        q = q.filter(CalendarEvent.end_at >= from_dt)
    if to_dt:
        q = q.filter(CalendarEvent.start_at <= to_dt)
    items = q.order_by(CalendarEvent.start_at.asc()).all()
    return ok({"items": [{"id": int(e.id), "scope": e.scope, "owner_user_id": e.owner_user_id, "project_id": e.project_id, "assignee_id": e.assignee_id, "title": e.title, "description_md": e.description_md, "start_at": e.start_at.isoformat(), "end_at": e.end_at.isoformat(), "all_day": bool(e.all_day), "location": e.location} for e in items]})


def validate_calendar_assignee(scope, project_id, assignee_id, actor_id):
    if assignee_id is None or assignee_id == "":
        return None, None
    try:
        assignee_id = int(assignee_id)
    except (ValueError, TypeError):
        return None, fail("VALIDATION_ERROR", "日程负责人无效", 400)
    assignee = db.session.get(User, assignee_id)
    if not assignee or assignee.status != "active" or not assignee.is_activated:
        return None, fail("VALIDATION_ERROR", "日程负责人不存在或未激活", 400)
    if scope == "personal" and assignee_id != int(actor_id) and not is_super_admin(actor_id):
        return None, fail("FORBIDDEN", "仅超级管理员可以给其他用户分配个人日程", 403)
    if scope == "project":
        project = db.session.get(Project, int(project_id)) if project_id else None
        member = ProjectMember.query.filter_by(project_id=project_id, user_id=assignee_id).first()
        if not project or (int(project.creator_id) != assignee_id and not member):
            return None, fail("VALIDATION_ERROR", "日程负责人必须是项目成员", 400)
    return assignee_id, None


@api_bp.post("/calendar/events")
@jwt_required()
def calendar_events_create():
    uid = current_user_id()
    body = request.get_json(silent=True) or {}
    scope = body.get("scope") or "personal"
    title = (body.get("title") or "").strip()
    start_at = parse_iso_datetime(body.get("start_at"))
    end_at = parse_iso_datetime(body.get("end_at"))
    if not title or not start_at or not end_at:
        return fail("VALIDATION_ERROR", "title/start_at/end_at 必填", 400)
    if as_utc(end_at) <= as_utc(start_at):
        return fail("VALIDATION_ERROR", "结束时间必须晚于开始时间", 400)
    assignee_id, err = validate_calendar_assignee(scope, body.get("project_id"), body.get("assignee_id"), uid)
    if err:
        return err
    if scope == "personal":
        e = CalendarEvent(scope="personal", owner_user_id=int(assignee_id or uid), assignee_id=assignee_id or int(uid), project_id=None, title=title, description_md=body.get("description_md"), start_at=start_at, end_at=end_at, all_day=bool(body.get("all_day")), location=body.get("location"), created_by=int(uid))
    elif scope == "project":
        project_id = body.get("project_id")
        if not project_id:
            return fail("VALIDATION_ERROR", "project_id 必填", 400)
        ok_role, _ = require_project_role(int(project_id), uid, "user")
        if not ok_role:
            return fail("FORBIDDEN", "无权限", 403)
        e = CalendarEvent(scope="project", owner_user_id=None, project_id=int(project_id), assignee_id=assignee_id, title=title, description_md=body.get("description_md"), start_at=start_at, end_at=end_at, all_day=bool(body.get("all_day")), location=body.get("location"), created_by=int(uid))
    else:
        return fail("VALIDATION_ERROR", "scope 非法", 400)
    db.session.add(e)
    db.session.flush()
    if assignee_id and int(assignee_id) != int(uid):
        notify(int(assignee_id), "calendar_assigned", f"你收到新日程：{e.title}", None, "/calendar", {"event_id": int(e.id)})
    if e.scope == "project":
        add_project_system_message(int(e.project_id), f"新建日程：{e.title}", int(uid))
    db.session.commit()
    return ok({"event": {"id": int(e.id)}})


@api_bp.patch("/calendar/events/<int:event_id>")
@jwt_required()
def calendar_events_patch(event_id: int):
    uid = current_user_id()
    e = CalendarEvent.query.get(event_id)
    if not e:
        return fail("NOT_FOUND", "事件不存在", 404)
    if e.scope == "personal":
        if int(e.owner_user_id or 0) != int(uid) and not is_super_admin(uid):
            return fail("FORBIDDEN", "无权限", 403)
    else:
        ok_role, _ = require_project_role(int(e.project_id), uid, "user")
        if not ok_role:
            return fail("FORBIDDEN", "无权限", 403)
    body = request.get_json(silent=True) or {}
    if "title" in body:
        v = (body.get("title") or "").strip()
        if v:
            e.title = v
    if "description_md" in body:
        e.description_md = body.get("description_md")
    if "start_at" in body:
        v = parse_iso_datetime(body.get("start_at"))
        if not v:
            return fail("VALIDATION_ERROR", "start_at 非法", 400)
        e.start_at = v
    if "end_at" in body:
        v = parse_iso_datetime(body.get("end_at"))
        if not v:
            return fail("VALIDATION_ERROR", "end_at 非法", 400)
        e.end_at = v
    if "all_day" in body:
        e.all_day = bool(body.get("all_day"))
    if "location" in body:
        e.location = body.get("location")
    if "assignee_id" in body:
        assignee_id, err = validate_calendar_assignee(e.scope, e.project_id, body.get("assignee_id"), uid)
        if err:
            return err
        e.assignee_id = assignee_id
        if e.scope == "personal" and assignee_id:
            e.owner_user_id = assignee_id
    if as_utc(e.end_at) <= as_utc(e.start_at):
        return fail("VALIDATION_ERROR", "结束时间必须晚于开始时间", 400)
    if e.assignee_id and int(e.assignee_id) != int(uid):
        notify(int(e.assignee_id), "calendar_updated", f"日程已更新：{e.title}", None, "/calendar", {"event_id": int(e.id)})
    if e.scope == "project":
        add_project_system_message(int(e.project_id), f"修改日程：{e.title}", int(uid))
    db.session.commit()
    return ok({})


@api_bp.delete("/calendar/events/<int:event_id>")
@jwt_required()
def calendar_events_delete(event_id: int):
    uid = current_user_id()
    e = CalendarEvent.query.get(event_id)
    if not e:
        return fail("NOT_FOUND", "事件不存在", 404)
    if e.scope == "personal":
        if int(e.owner_user_id or 0) != int(uid) and not is_super_admin(uid):
            return fail("FORBIDDEN", "无权限", 403)
    else:
        ok_role, _ = require_project_role(int(e.project_id), uid, "user")
        if not ok_role:
            return fail("FORBIDDEN", "无权限", 403)
    db.session.delete(e)
    db.session.commit()
    return ok({})


def can_access_inbox_thread(thread, user_id, write=False):
    if not thread:
        return False
    if thread.type == "project_group":
        try:
            project_id = int((thread.subject or "").split(":", 1)[1])
        except (IndexError, TypeError, ValueError):
            return False
        if thread.subject != f"project:{project_id}" or not db.session.get(Project, project_id):
            return False
        # A historical InboxRecipient does not preserve project access after exit.
        role = project_role(project_id, int(user_id))
        return role in ("user", "admin", "creator") if write else role is not None
    if write and thread.type != "direct":
        return False
    recipient = InboxRecipient.query.filter_by(thread_id=int(thread.id), user_id=int(user_id)).first()
    return bool(recipient) or (not write and is_super_admin(user_id))


@api_bp.get("/inbox/threads")
@jwt_required()
def inbox_threads_list():
    uid = current_user_id()
    thread_ids = (
        db.session.query(InboxRecipient.thread_id)
        .filter(InboxRecipient.user_id == int(uid))
        .subquery()
    )
    threads = InboxThread.query.filter(InboxThread.id.in_(thread_ids)).order_by(InboxThread.id.desc()).all()
    project_ids = []
    for t in threads:
        if t.type == "project_group" and (t.subject or "").startswith("project:"):
            try:
                project_ids.append(int((t.subject or "").split(":", 1)[1]))
            except Exception:
                continue
    projects = {int(p.id): p for p in Project.query.filter(Project.id.in_(list(set(project_ids)))).all()} if project_ids else {}
    items = []
    for t in threads:
        if not can_access_inbox_thread(t, uid):
            continue
        subject = t.subject
        if t.type == "project_group" and (subject or "").startswith("project:"):
            try:
                pid = int((subject or "").split(":", 1)[1])
                p = projects.get(pid)
                if p:
                    subject = f"项目:{p.name}"
            except Exception:
                pass
        last_msg = (
            InboxMessage.query.filter_by(thread_id=int(t.id))
            .order_by(InboxMessage.id.desc())
            .first()
        )
        items.append(
            {
                "id": int(t.id),
                "type": t.type,
                "subject": subject,
                "created_by": int(t.created_by),
                "updated_at": t.updated_at.isoformat(),
                "last_message": {"id": int(last_msg.id), "sender_id": int(last_msg.sender_id), "created_at": last_msg.created_at.isoformat()} if last_msg else None,
            }
        )
    return ok({"items": items})


@api_bp.post("/inbox/threads")
@jwt_required()
def inbox_threads_create():
    uid = current_user_id()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return fail("VALIDATION_ERROR", "请求内容无效", 400)
    if body.get("type", "direct") != "direct":
        return fail("FORBIDDEN", "客户端只能创建私聊会话", 403)
    recipients = body.get("recipients") or []
    subject = body.get("subject") or ""
    content_md = body.get("content_md") or ""
    if not isinstance(recipients, list) or len(recipients) == 0:
        return fail("VALIDATION_ERROR", "recipients 必填", 400)
    if not isinstance(subject, str) or not isinstance(content_md, str) or len(subject) > 255:
        return fail("VALIDATION_ERROR", "会话标题或消息内容无效", 400)
    recipient_ids = set()
    for value in recipients:
        if isinstance(value, bool) or not isinstance(value, (int, str)) or (isinstance(value, str) and not value.strip().isdecimal()):
            return fail("VALIDATION_ERROR", "收件人编号无效", 400)
        try:
            recipient_id = int(value)
        except (TypeError, ValueError):
            return fail("VALIDATION_ERROR", "收件人编号无效", 400)
        if not 0 < recipient_id < 2 ** 63:
            return fail("VALIDATION_ERROR", "收件人编号无效", 400)
        recipient_ids.add(recipient_id)
    valid_ids = {int(user.id) for user in User.query.filter(
        User.id.in_(recipient_ids), User.status == "active", User.is_activated.is_(True),
    ).all()}
    if valid_ids != recipient_ids:
        return fail("VALIDATION_ERROR", "收件人不存在、未激活或已停用", 400)
    t = InboxThread(type="direct", subject=subject.strip() or None, created_by=int(uid))
    db.session.add(t)
    db.session.flush()
    db.session.add(InboxRecipient(thread_id=int(t.id), user_id=int(uid), last_read_at=utcnow()))
    for rid in recipient_ids - {int(uid)}:
        db.session.add(InboxRecipient(thread_id=int(t.id), user_id=int(rid), last_read_at=None))
    m = InboxMessage(thread_id=int(t.id), sender_id=int(uid), content_md=content_md or "")
    db.session.add(m)
    t.updated_at = utcnow()
    mention_ids = parse_mentions(content_md or "")
    for rid in recipient_ids - {int(uid)}:
        notify(int(rid), "inbox_message", "你收到一条新站内信", None, f"/inbox?thread={t.id}", {"thread_id": int(t.id), "message_id": None})
    for mid in mention_ids:
        if int(mid) != int(uid):
            notify(int(mid), "mention", "你在站内信中被提及", None, f"/inbox?thread={t.id}", {"thread_id": int(t.id)})
    db.session.commit()
    return ok({"thread": {"id": int(t.id)}})


@api_bp.get("/inbox/threads/<int:thread_id>/messages")
@jwt_required()
def inbox_messages_list(thread_id: int):
    uid = current_user_id()
    t = InboxThread.query.get(int(thread_id))
    if not can_access_inbox_thread(t, uid):
        return fail("FORBIDDEN", "无权限", 403)
    is_system = bool(t and t.type == "system")
    items = InboxMessage.query.filter_by(thread_id=thread_id).order_by(InboxMessage.id.asc()).all()
    if is_system:
        return ok({"items": [{"id": int(x.id), "sender_id": int(x.sender_id), "sender_name": "Server", "content_md": x.content_md, "created_at": x.created_at.isoformat()} for x in items]})
    sender_ids = {int(x.sender_id) for x in items}
    users = {int(u.id): u for u in User.query.filter(User.id.in_(list(sender_ids))).all()} if sender_ids else {}
    out = []
    for x in items:
        su = users.get(int(x.sender_id))
        out.append({"id": int(x.id), "sender_id": int(x.sender_id), "sender_name": (su.display_name if su else None), "content_md": x.content_md, "created_at": x.created_at.isoformat()})
    return ok({"items": out})


@api_bp.post("/inbox/threads/<int:thread_id>/messages")
@jwt_required()
def inbox_messages_create(thread_id: int):
    uid = current_user_id()
    t = db.session.get(InboxThread, int(thread_id))
    if not can_access_inbox_thread(t, uid, write=True):
        return fail("FORBIDDEN", "无权限", 403)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return fail("VALIDATION_ERROR", "请求内容无效", 400)
    content_md = body.get("content_md") or ""
    if not isinstance(content_md, str) or not content_md.strip():
        return fail("VALIDATION_ERROR", "content_md 必填", 400)
    m = InboxMessage(thread_id=thread_id, sender_id=int(uid), content_md=content_md)
    db.session.add(m)
    t.updated_at = utcnow()
    recs = InboxRecipient.query.filter_by(thread_id=thread_id).all()
    mention_ids = parse_mentions(content_md)
    for r in recs:
        if int(r.user_id) != int(uid):
            notify(int(r.user_id), "inbox_message", "你收到一条新站内信", None, f"/inbox?thread={thread_id}", {"thread_id": int(thread_id), "message_id": None})
    for mid in mention_ids:
        if int(mid) != int(uid):
            notify(int(mid), "mention", "你在站内信中被提及", None, f"/inbox?thread={thread_id}", {"thread_id": int(thread_id)})
    db.session.commit()
    return ok({"message": {"id": int(m.id)}})


@api_bp.post("/inbox/threads/<int:thread_id>/read")
@jwt_required()
def inbox_thread_read(thread_id: int):
    uid = current_user_id()
    t = db.session.get(InboxThread, int(thread_id))
    if not can_access_inbox_thread(t, uid):
        return fail("FORBIDDEN", "无权限", 403)
    rec = InboxRecipient.query.filter_by(thread_id=thread_id, user_id=int(uid)).first()
    if rec:
        rec.last_read_at = utcnow()
        db.session.commit()
    return ok({})


@api_bp.get("/notifications")
@jwt_required()
def notifications_list():
    uid = current_user_id()
    page = int(request.args.get("page", "1"))
    page_size = min(int(request.args.get("page_size", "50")), 100)
    q = Notification.query.filter_by(user_id=int(uid)).order_by(Notification.id.desc())
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    total = q.count()
    return ok({"items": [{"id": int(n.id), "type": n.type, "title": n.title, "content": n.content, "link_url": n.link_url, "meta": n.meta_json, "read_at": n.read_at.isoformat() if n.read_at else None, "created_at": n.created_at.isoformat()} for n in items], "total": total, "page": page, "page_size": page_size})


@api_bp.post("/notifications/<int:notification_id>/read")
@jwt_required()
def notifications_read(notification_id: int):
    uid = current_user_id()
    n = Notification.query.get(notification_id)
    if not n or int(n.user_id) != int(uid):
        return fail("NOT_FOUND", "通知不存在", 404)
    n.read_at = utcnow()
    db.session.commit()
    return ok({})


@api_bp.post("/notifications/read-all")
@jwt_required()
def notifications_read_all():
    uid = current_user_id()
    Notification.query.filter_by(user_id=int(uid), read_at=None).update({"read_at": utcnow()})
    db.session.commit()
    return ok({})


@api_bp.get("/admin/overview")
@jwt_required()
def admin_overview():
    uid = current_user_id()
    if not is_super_admin(uid):
        return fail("FORBIDDEN", "无权限", 403)
    users_count = User.query.count()
    projects_count = Project.query.count()
    storage_bytes = db.session.query(db.func.sum(StorageObject.size_bytes)).scalar() or 0
    return ok({"users": users_count, "projects": projects_count, "storage_bytes": int(storage_bytes)})


@api_bp.get("/admin/projects")
@jwt_required()
def admin_projects():
    uid = current_user_id()
    if not is_super_admin(uid):
        return fail("FORBIDDEN", "无权限", 403)
    items = Project.query.order_by(Project.id.desc()).limit(200).all()
    return ok({"items": [to_project(p, None) for p in items]})


@api_bp.get("/admin/storage")
@jwt_required()
def admin_storage():
    uid = current_user_id()
    if not is_super_admin(uid):
        return fail("FORBIDDEN", "无权限", 403)
    storage_bytes = db.session.query(db.func.sum(StorageObject.size_bytes)).scalar() or 0
    objects_count = StorageObject.query.count()
    nodes_count = FileNode.query.filter(FileNode.deleted_at.is_(None)).count()
    files_count = FileNode.query.filter(FileNode.deleted_at.is_(None), FileNode.type == "file").count()
    folders_count = FileNode.query.filter(FileNode.deleted_at.is_(None), FileNode.type == "folder").count()
    deleted_nodes_count = FileNode.query.filter(FileNode.deleted_at.isnot(None)).count()
    largest_object_bytes = db.session.query(db.func.max(StorageObject.size_bytes)).scalar() or 0
    avg_object_size = int(int(storage_bytes) / int(objects_count)) if int(objects_count) else 0

    logical_bytes = (
        db.session.query(func.coalesce(func.sum(StorageObject.size_bytes), 0))
        .select_from(FileNode)
        .join(StorageObject, StorageObject.id == FileNode.storage_object_id)
        .filter(FileNode.deleted_at.is_(None), FileNode.type == "file")
        .scalar()
        or 0
    )

    scope_bytes_rows = (
        db.session.query(
            FileNode.scope,
            func.count(FileNode.id),
            func.coalesce(func.sum(StorageObject.size_bytes), 0),
        )
        .select_from(FileNode)
        .join(StorageObject, StorageObject.id == FileNode.storage_object_id)
        .filter(FileNode.deleted_at.is_(None), FileNode.type == "file")
        .group_by(FileNode.scope)
        .all()
    )
    scope_folder_rows = {
        scope: int(cnt)
        for scope, cnt in db.session.query(FileNode.scope, func.count(FileNode.id))
        .filter(FileNode.deleted_at.is_(None), FileNode.type == "folder")
        .group_by(FileNode.scope)
        .all()
    }
    scopes = [
        {
            "scope": scope or "unknown",
            "files_count": int(file_count or 0),
            "folders_count": int(scope_folder_rows.get(scope, 0)),
            "storage_bytes": int(size or 0),
        }
        for scope, file_count, size in scope_bytes_rows
    ]

    def mime_category(mime_type):
        value = (mime_type or "").lower()
        if value.startswith("image/"):
            return "图片"
        if value.startswith("video/"):
            return "视频"
        if value.startswith("audio/"):
            return "音频"
        if value in ("application/pdf",):
            return "PDF"
        if "zip" in value or "rar" in value or "7z" in value or "tar" in value or "compressed" in value:
            return "压缩包"
        if "spreadsheet" in value or "excel" in value:
            return "表格"
        if "presentation" in value or "powerpoint" in value:
            return "演示文稿"
        if "word" in value or "document" in value:
            return "文档"
        if value.startswith("text/"):
            return "文本"
        return "其他"

    type_map = {}
    for mime_type, cnt, size in (
        db.session.query(
            StorageObject.mime_type,
            func.count(StorageObject.id),
            func.coalesce(func.sum(StorageObject.size_bytes), 0),
        )
        .group_by(StorageObject.mime_type)
        .all()
    ):
        key = mime_category(mime_type)
        item = type_map.setdefault(key, {"type": key, "objects_count": 0, "storage_bytes": 0})
        item["objects_count"] += int(cnt or 0)
        item["storage_bytes"] += int(size or 0)
    types = sorted(type_map.values(), key=lambda x: x["storage_bytes"], reverse=True)

    top_projects = [
        {
            "project_id": int(project_id),
            "name": name or f"项目 #{int(project_id)}",
            "files_count": int(file_count or 0),
            "storage_bytes": int(size or 0),
        }
        for project_id, name, file_count, size in (
            db.session.query(
                FileNode.project_id,
                Project.name,
                func.count(FileNode.id),
                func.coalesce(func.sum(StorageObject.size_bytes), 0),
            )
            .select_from(FileNode)
            .join(StorageObject, StorageObject.id == FileNode.storage_object_id)
            .outerjoin(Project, Project.id == FileNode.project_id)
            .filter(FileNode.deleted_at.is_(None), FileNode.type == "file", FileNode.project_id.isnot(None))
            .group_by(FileNode.project_id, Project.name)
            .order_by(func.coalesce(func.sum(StorageObject.size_bytes), 0).desc())
            .limit(8)
            .all()
        )
    ]

    top_users = [
        {
            "user_id": int(user_id),
            "name": display_name or username or f"用户 #{int(user_id)}",
            "files_count": int(file_count or 0),
            "storage_bytes": int(size or 0),
        }
        for user_id, username, display_name, file_count, size in (
            db.session.query(
                FileNode.created_by,
                User.username,
                User.display_name,
                func.count(FileNode.id),
                func.coalesce(func.sum(StorageObject.size_bytes), 0),
            )
            .select_from(FileNode)
            .join(StorageObject, StorageObject.id == FileNode.storage_object_id)
            .outerjoin(User, User.id == FileNode.created_by)
            .filter(FileNode.deleted_at.is_(None), FileNode.type == "file")
            .group_by(FileNode.created_by, User.username, User.display_name)
            .order_by(func.coalesce(func.sum(StorageObject.size_bytes), 0).desc())
            .limit(8)
            .all()
        )
    ]

    duplicate_objects_count = 0
    duplicate_reclaimable_bytes = 0
    duplicate_rows = (
        db.session.query(
            StorageObject.sha256,
            StorageObject.size_bytes,
            func.count(StorageObject.id),
        )
        .filter(StorageObject.sha256.isnot(None), StorageObject.sha256 != "")
        .group_by(StorageObject.sha256, StorageObject.size_bytes)
        .having(func.count(StorageObject.id) > 1)
        .all()
    )
    for _, size, cnt in duplicate_rows:
        duplicate_objects_count += max(0, int(cnt or 0) - 1)
        duplicate_reclaimable_bytes += max(0, int(cnt or 0) - 1) * int(size or 0)

    return ok(
        {
            "storage_bytes": int(storage_bytes),
            "logical_bytes": int(logical_bytes),
            "objects_count": int(objects_count),
            "nodes_count": int(nodes_count),
            "files_count": int(files_count),
            "folders_count": int(folders_count),
            "deleted_nodes_count": int(deleted_nodes_count),
            "largest_object_bytes": int(largest_object_bytes),
            "avg_object_size": int(avg_object_size),
            "duplicate_objects_count": int(duplicate_objects_count),
            "duplicate_reclaimable_bytes": int(duplicate_reclaimable_bytes),
            "scopes": scopes,
            "types": types,
            "top_projects": top_projects,
            "top_users": top_users,
        }
    )


@api_bp.get("/admin/invite-codes")
@jwt_required()
def admin_invite_codes_list():
    uid = current_user_id()
    if not is_super_admin(uid):
        return fail("FORBIDDEN", "无权限", 403)
    items = InviteCode.query.order_by(InviteCode.id.desc()).limit(500).all()
    return ok(
        {
            "items": [
                {
                    "id": int(x.id),
                    "code": x.code,
                    "enabled": bool(x.enabled),
                    "note": x.note,
                    "used_count": int(x.used_count or 0),
                    "max_uses": int(x.max_uses) if x.max_uses is not None else None,
                    "created_by": int(x.created_by) if x.created_by else None,
                    "created_at": x.created_at.isoformat(),
                    "updated_at": x.updated_at.isoformat(),
                }
                for x in items
            ]
        }
    )


@api_bp.post("/admin/invite-codes")
@jwt_required()
def admin_invite_codes_create():
    uid = current_user_id()
    if not is_super_admin(uid):
        return fail("FORBIDDEN", "无权限", 403)
    body = request.get_json(silent=True) or {}
    code = (body.get("code") or "").strip()
    if not code:
        return fail("VALIDATION_ERROR", "邀请码必填", 400)
    if len(code) < 4:
        return fail("VALIDATION_ERROR", "邀请码过短", 400)
    if InviteCode.query.filter_by(code=code).first():
        return fail("CONFLICT", "邀请码已存在", 409)
    max_uses = body.get("max_uses")
    if max_uses is not None:
        try:
            max_uses = int(max_uses)
        except Exception:
            return fail("VALIDATION_ERROR", "max_uses 非法", 400)
        if max_uses < 0:
            return fail("VALIDATION_ERROR", "max_uses 非法", 400)
        if max_uses == 0:
            max_uses = 0
    row = InviteCode(
        code=code,
        enabled=True,
        note=(body.get("note") or None),
        created_by=int(uid),
        used_count=0,
        max_uses=max_uses,
    )
    db.session.add(row)
    db.session.commit()
    return ok({"invite_code": {"id": int(row.id), "code": row.code}})


@api_bp.patch("/admin/invite-codes/<int:invite_id>")
@jwt_required()
def admin_invite_codes_patch(invite_id: int):
    uid = current_user_id()
    if not is_super_admin(uid):
        return fail("FORBIDDEN", "无权限", 403)
    row = InviteCode.query.get(int(invite_id))
    if not row:
        return fail("NOT_FOUND", "邀请码不存在", 404)
    body = request.get_json(silent=True) or {}
    if "enabled" in body:
        row.enabled = bool(body.get("enabled"))
    if "max_uses" in body:
        v = body.get("max_uses")
        if v is None or v == "":
            row.max_uses = None
        else:
            try:
                n = int(v)
            except Exception:
                return fail("VALIDATION_ERROR", "max_uses 非法", 400)
            if n < 0:
                return fail("VALIDATION_ERROR", "max_uses 非法", 400)
            row.max_uses = n
    if "note" in body:
        row.note = body.get("note") or None
    db.session.commit()
    return ok(
        {
            "invite_code": {
                "id": int(row.id),
                "code": row.code,
                "enabled": bool(row.enabled),
                "note": row.note,
                "used_count": int(row.used_count or 0),
                "max_uses": int(row.max_uses) if row.max_uses is not None else None,
                "created_by": int(row.created_by) if row.created_by else None,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
        }
    )


@api_bp.post("/admin/users/<int:user_id>/activate")
@jwt_required()
def admin_user_activate(user_id: int):
    uid = current_user_id()
    if not is_super_admin(uid):
        return fail("FORBIDDEN", "无权限", 403)
    u = User.query.get(user_id)
    if not u:
        return fail("NOT_FOUND", "用户不存在", 404)
    if u.status != "active":
        return fail("CONFLICT", "账号状态异常", 409)
    if bool(u.is_activated):
        return ok({"user": to_user(u)})
    u.is_activated = True
    notify(int(u.id), "user_activated", "管理员已通过审核，你可以登录了", None, "/login", None)
    db.session.commit()
    return ok({"user": to_user(u)})


def admin_user_stats(user_ids: list[int]):
    if not user_ids:
        return {}, {}, {}, {}, {}, {}, {}, {}

    uploads_count = {
        int(uid): int(cnt)
        for uid, cnt in db.session.query(FileNode.created_by, func.count(FileNode.id))
        .filter(
            FileNode.deleted_at.is_(None),
            FileNode.type == "file",
            FileNode.created_by.in_(user_ids),
        )
        .group_by(FileNode.created_by)
        .all()
    }
    uploads_bytes = {
        int(uid): int(sz or 0)
        for uid, sz in db.session.query(FileNode.created_by, func.coalesce(func.sum(StorageObject.size_bytes), 0))
        .select_from(FileNode)
        .join(StorageObject, StorageObject.id == FileNode.storage_object_id)
        .filter(
            FileNode.deleted_at.is_(None),
            FileNode.type == "file",
            FileNode.created_by.in_(user_ids),
        )
        .group_by(FileNode.created_by)
        .all()
    }
    tasks_completed = {
        int(uid): int(cnt)
        for uid, cnt in db.session.query(Task.assignee_id, func.count(Task.id))
        .filter(Task.assignee_id.isnot(None), Task.completed_at.isnot(None), Task.assignee_id.in_(user_ids))
        .group_by(Task.assignee_id)
        .all()
    }
    tasks_reported = {
        int(uid): int(cnt)
        for uid, cnt in db.session.query(Task.reporter_id, func.count(Task.id))
        .filter(Task.reporter_id.in_(user_ids))
        .group_by(Task.reporter_id)
        .all()
    }
    projects_created = {
        int(uid): int(cnt)
        for uid, cnt in db.session.query(Project.creator_id, func.count(Project.id))
        .filter(Project.creator_id.in_(user_ids))
        .group_by(Project.creator_id)
        .all()
    }
    memberships = {
        int(uid): int(cnt)
        for uid, cnt in db.session.query(ProjectMember.user_id, func.count(ProjectMember.id))
        .filter(ProjectMember.user_id.in_(user_ids))
        .group_by(ProjectMember.user_id)
        .all()
    }
    inbox_sent = {
        int(uid): int(cnt)
        for uid, cnt in db.session.query(InboxMessage.sender_id, func.count(InboxMessage.id))
        .filter(InboxMessage.sender_id != 0, InboxMessage.sender_id.in_(user_ids))
        .group_by(InboxMessage.sender_id)
        .all()
    }
    approvals_sent = {
        int(uid): int(cnt)
        for uid, cnt in db.session.query(InviteCode.created_by, func.count(InviteCode.id))
        .filter(InviteCode.created_by.isnot(None), InviteCode.created_by.in_(user_ids))
        .group_by(InviteCode.created_by)
        .all()
    }
    return (
        uploads_count,
        uploads_bytes,
        tasks_completed,
        tasks_reported,
        projects_created,
        memberships,
        inbox_sent,
        approvals_sent,
    )


@api_bp.get("/admin/users")
@jwt_required()
def admin_users_list():
    uid = current_user_id()
    if not is_super_admin(uid):
        return fail("FORBIDDEN", "无权限", 403)
    q0 = (request.args.get("q") or "").strip()
    page = int(request.args.get("page", "1"))
    page_size = min(int(request.args.get("page_size", "50")), 200)
    q = User.query.order_by(User.id.desc())
    if q0:
        like = f"%{q0}%"
        q = q.filter(or_(User.username.ilike(like), User.display_name.ilike(like), User.email.ilike(like)))
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    total = q.count()
    ids = [int(x.id) for x in items]
    (
        uploads_count,
        uploads_bytes,
        tasks_completed,
        tasks_reported,
        projects_created,
        memberships,
        inbox_sent,
        approvals_sent,
    ) = admin_user_stats(ids)
    out = []
    for u in items:
        uid2 = int(u.id)
        out.append(
            {
                **to_user(u),
                "stats": {
                    "uploads_count": int(uploads_count.get(uid2, 0)),
                    "uploads_bytes": int(uploads_bytes.get(uid2, 0)),
                    "tasks_completed": int(tasks_completed.get(uid2, 0)),
                    "tasks_reported": int(tasks_reported.get(uid2, 0)),
                    "projects_created": int(projects_created.get(uid2, 0)),
                    "memberships": int(memberships.get(uid2, 0)),
                    "inbox_sent": int(inbox_sent.get(uid2, 0)),
                    "invite_codes_created": int(approvals_sent.get(uid2, 0)),
                },
            }
        )
    return ok({"items": out, "total": int(total), "page": page, "page_size": page_size})


def admin_get_user_or_404(user_id: int):
    u = User.query.get(int(user_id))
    if not u:
        return None, fail("NOT_FOUND", "用户不存在", 404)
    return u, None


@api_bp.post("/admin/users/<int:user_id>/disable")
@jwt_required()
def admin_user_disable(user_id: int):
    uid = current_user_id()
    if not is_super_admin(uid):
        return fail("FORBIDDEN", "无权限", 403)
    if int(uid) == int(user_id):
        return fail("CONFLICT", "不能操作自己", 409)
    u, err = admin_get_user_or_404(user_id)
    if err:
        return err
    u.status = "disabled"
    revoke_user_sessions(u.id)
    db.session.commit()
    return ok({"user": to_user(u)})


@api_bp.post("/admin/users/<int:user_id>/enable")
@jwt_required()
def admin_user_enable(user_id: int):
    uid = current_user_id()
    if not is_super_admin(uid):
        return fail("FORBIDDEN", "无权限", 403)
    u, err = admin_get_user_or_404(user_id)
    if err:
        return err
    if u.status == "deleted":
        return fail("CONFLICT", "账号已删除", 409)
    u.status = "active"
    db.session.commit()
    return ok({"user": to_user(u)})


@api_bp.post("/admin/users/<int:user_id>/set-super-admin")
@jwt_required()
def admin_user_set_super_admin(user_id: int):
    uid = current_user_id()
    if not is_super_admin(uid):
        return fail("FORBIDDEN", "无权限", 403)
    u, err = admin_get_user_or_404(user_id)
    if err:
        return err
    if u.status == "deleted":
        return fail("CONFLICT", "账号已删除", 409)
    u.role_system = "super_admin"
    db.session.commit()
    return ok({"user": to_user(u)})


@api_bp.post("/admin/users/<int:user_id>/set-user")
@jwt_required()
def admin_user_set_user(user_id: int):
    uid = current_user_id()
    if not is_super_admin(uid):
        return fail("FORBIDDEN", "无权限", 403)
    if int(uid) == int(user_id):
        return fail("CONFLICT", "不能操作自己", 409)
    u, err = admin_get_user_or_404(user_id)
    if err:
        return err
    if u.status == "deleted":
        return fail("CONFLICT", "账号已删除", 409)
    u.role_system = "user"
    db.session.commit()
    return ok({"user": to_user(u)})


@api_bp.delete("/admin/users/<int:user_id>")
@jwt_required()
def admin_user_delete(user_id: int):
    uid = current_user_id()
    if not is_super_admin(uid):
        return fail("FORBIDDEN", "无权限", 403)
    if int(uid) == int(user_id):
        return fail("CONFLICT", "不能删除自己", 409)
    u, err = admin_get_user_or_404(user_id)
    if err:
        return err
    u.status = "deleted"
    u.is_activated = False
    revoke_user_sessions(u.id)
    db.session.commit()
    return ok({"user": to_user(u)})
