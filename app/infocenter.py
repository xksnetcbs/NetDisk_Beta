"""Authenticated, allow-listed proxy to the private InfoCenter service."""

import json
import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request

from flask import Blueprint, Response, abort, current_app, jsonify, make_response, request, stream_with_context
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request

from .extensions import db
from .auth_sessions import as_utc, is_live_session
from .models import AuthRefreshToken, InboxMessage, InboxRecipient, InboxThread, MessageBridgeOutbox, Project, ProjectMember, User, utcnow


infocenter_bp = Blueprint("infocenter", __name__)
MAX_REQUEST_BYTES = 30 * 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024
READ_DESKTOP = re.compile(r"(?:status|conversations|messages|messages/[0-9]+/(?:file|media))\Z")
WRITE_DESKTOP = re.compile(r"send/(?:prepare|select|submit|cancel|status)\Z")
READ_TERMINAL = re.compile(r"(?:snapshot|messages|unread)\Z")
WRITE_TERMINAL = re.compile(r"(?:messages/[0-9]+/read|messages/read-all|conversations/read)\Z")
RESPONSE_HEADERS = ("Content-Type", "Content-Length", "Content-Disposition", "Accept-Ranges", "Content-Range")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, _req, _fp, _code, _msg, _headers, _newurl):
        return None


def proxy_error(message, status):
    return jsonify(error=message), status


@infocenter_bp.before_request
def require_super_admin():
    if request.method == "OPTIONS":
        return current_app.make_default_options_response()
    # This also invokes NetDisk's device-session revocation callback.
    verify_jwt_in_request()
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return proxy_error("登录已失效，请重新登录", 401)
    user = db.session.get(User, user_id)
    if not user or user.status != "active" or not user.is_activated:
        return proxy_error("账号未激活或已停用", 403)
    if user.role_system != "super_admin":
        return proxy_error("只有超级管理员可以访问信息中心", 403)


def upstream_configuration():
    base = str(current_app.config.get("INFOCENTER_API_BASE") or "").rstrip("/")
    token = str(current_app.config.get("INFOCENTER_API_TOKEN") or "")
    parsed = urllib.parse.urlsplit(base)
    if not token or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("InfoCenter 服务连接尚未配置")
    if parsed.scheme not in ("http", "https"):
        raise ValueError("InfoCenter 服务地址无效")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("远程 InfoCenter 服务必须使用 HTTPS")
    return base, token


def open_upstream(url, token, body=None, method=None):
    headers = {"Authorization": "Bearer " + token, "Accept-Encoding": "identity"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if request.headers.get("Range"):
        headers["Range"] = request.headers["Range"]
    upstream = urllib.request.Request(url, data=body, headers=headers, method=method or request.method)
    timeout = float(current_app.config.get("INFOCENTER_TIMEOUT", 45))
    return urllib.request.build_opener(NoRedirect).open(upstream, timeout=timeout)


def lock_reply_actor():
    """Revalidate the device and account with current reads after waiting for locks."""
    db.session.rollback()
    verify_jwt_in_request()
    user = User.query.filter_by(id=int(get_jwt_identity())).populate_existing().with_for_update().first()
    claims = get_jwt()
    valid = bool(user and user.status == "active" and user.is_activated
                 and claims.get("exp", 0) > utcnow().timestamp())
    session_id = claims.get("auth_session")
    if session_id is not None:
        try:
            session = AuthRefreshToken.query.filter_by(id=int(session_id)).populate_existing().with_for_update().first()
            valid = valid and is_live_session(session) and int(session.user_id) == int(user.id)
        except (TypeError, ValueError):
            valid = False
    elif valid:
        revoked = AuthRefreshToken.query.filter(AuthRefreshToken.user_id == user.id,
            AuthRefreshToken.revoked_at.isnot(None)).order_by(AuthRefreshToken.revoked_at.desc()).populate_existing().with_for_update().first()
        valid = not revoked or claims["iat"] > as_utc(revoked.revoked_at).timestamp()
    if not valid:
        db.session.rollback()
        abort(make_response(jsonify(error="登录已失效，请重新登录"), 401))
    return user


def netdisk_reply_target(chat_id, message_uid, user):
    """Resolve the real local conversation, never exported recipient snapshots."""
    from .message_bridge import instance_id
    if not isinstance(chat_id, str) or not chat_id.startswith("netdisk:") or not isinstance(message_uid, str) or not 1 <= len(message_uid) <= 200:
        return None, None, proxy_error("缺少有效站内会话来源", 400)
    source = MessageBridgeOutbox.query.filter_by(event_uid=message_uid).populate_existing().first()
    if not source:
        return None, None, proxy_error("站内会话来源不存在", 404)
    metadata = source.payload_json or {}
    if metadata.get("source") != "netdisk" or metadata.get("instance_id") != instance_id() or metadata.get("chat_id") != chat_id:
        return None, None, proxy_error("站内会话来源不匹配", 403)
    kind = metadata.get("thread_type")
    if kind not in ("project_group", "direct"):
        return None, None, proxy_error("系统通知不能回复，请使用消息中的详情入口", 403)
    try:
        thread_id = int(metadata["thread_id"]) if metadata.get("thread_id") else None
        project_id = int(metadata["project_id"]) if metadata.get("project_id") else None
    except (ValueError, TypeError):
        return None, None, proxy_error("站内会话来源无效", 403)
    if kind == "project_group":
        project = Project.query.filter_by(id=project_id).populate_existing().with_for_update().first() if project_id else None
        if not project:
            return None, None, proxy_error("项目会话来源不匹配", 403)
        member = ProjectMember.query.filter_by(project_id=project.id, user_id=user.id).populate_existing().with_for_update().first()
        if user.role_system != "super_admin" and int(project.creator_id) != int(user.id) and (not member or member.role_project not in ("user", "admin", "creator")):
            return None, None, proxy_error("无权限向此项目发送消息", 403)
        thread = InboxThread.query.filter_by(id=thread_id).populate_existing().with_for_update().first() if thread_id else None
        if thread and (thread.type != kind or thread.subject != f"project:{project.id}"):
            return None, None, proxy_error("项目会话来源不匹配", 403)
        if not thread:
            thread = InboxThread.query.filter_by(type="project_group", subject=f"project:{project.id}").order_by(InboxThread.id).populate_existing().with_for_update().first()
        return thread, project, None
    thread = InboxThread.query.filter_by(id=thread_id).populate_existing().with_for_update().first() if thread_id else None
    if not thread or thread.type != "direct":
        return None, None, proxy_error("站内会话不存在", 404)
    participant = InboxRecipient.query.filter_by(thread_id=thread.id, user_id=user.id).populate_existing().with_for_update().first()
    if not participant:
        return None, None, proxy_error("只有私聊参与者可以回复", 403)
    return thread, None, None


@infocenter_bp.post("/netdisk/conversations/<path:chat_id>/send")
def send_netdisk_reply(chat_id):
    """Reply to a canonical NetDisk conversation without invoking WeChat."""
    from .api import add_project_group_message
    from .message_bridge import enqueue_inbox_message
    from .services import notify, parse_mentions

    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return proxy_error("请求内容无效", 400)
    text, request_id = body.get("text"), body.get("id")
    if not isinstance(text, str) or not text.strip() or len(text) > 4000 or "\x00" in text:
        return proxy_error("请输入 1 至 4000 字的站内消息", 400)
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", request_id):
        return proxy_error("缺少有效发送请求编号", 400)
    if body.get("attachment"):
        return proxy_error("站内会话当前仅支持文字", 400)
    message_uid = body.get("message_uid")
    if not isinstance(message_uid, str) or not 1 <= len(message_uid) <= 200:
        return proxy_error("缺少有效站内会话来源", 400)
    user = lock_reply_actor()
    user_id = int(user.id)
    if request.blueprint == "infocenter" and user.role_system != "super_admin":
        return proxy_error("只有超级管理员可以访问信息中心", 403)
    thread, project, error = netdisk_reply_target(chat_id, message_uid, user)
    if error:
        return error
    # User lock serializes this sender's retries; a unique indexed current read
    # avoids locking all unrelated outbox rows through a JSON table scan.
    request_key = hashlib.sha256(f"{user_id}:{request_id}".encode()).hexdigest()
    receipt = MessageBridgeOutbox.query.filter_by(reply_request_key=request_key).populate_existing().with_for_update().first()
    if not receipt:
        # Immutable pre-migration receipts retain their prior idempotency behavior.
        receipt = MessageBridgeOutbox.query.filter(
            MessageBridgeOutbox.reply_request_key.is_(None), MessageBridgeOutbox.event_kind == "inbox",
            MessageBridgeOutbox.payload_json["reply_request_id"].as_string() == request_id,
        ).populate_existing().first()
    if receipt:
        previous = receipt.payload_json
        if previous.get("chat_id") != chat_id or int(previous.get("sender_user_id", 0)) != user_id or previous.get("content") != text:
            return proxy_error("请求编号已用于其他消息", 409)
        return jsonify(status="confirmed", source="netdisk", message_id=int(receipt.source_id))
    if project:
        thread_id = add_project_group_message(int(project.id), user_id, text)
        message = next(row for row in db.session.new if isinstance(row, InboxMessage) and int(row.thread_id) == thread_id)
        thread = db.session.get(InboxThread, int(thread_id))
    else:
        message = InboxMessage(thread_id=int(thread.id), sender_id=user_id, content_md=text)
        db.session.add(message)
        thread.updated_at = utcnow()
    for recipient in InboxRecipient.query.filter_by(thread_id=int(thread.id)).all():
        if not project and int(recipient.user_id) != user_id:
            notify(int(recipient.user_id), "inbox_message", "你收到一条新站内信", None,
                   f"/inbox?thread={thread.id}", {"thread_id": int(thread.id)})
    for mentioned in parse_mentions(text):
        if int(mentioned) != user_id:
            notify(int(mentioned), "mention", "你在消息中被提及", None,
                   f"/projects/{project.id}" if project else f"/inbox?thread={thread.id}", {"thread_id": int(thread.id)})
    db.session.flush()
    outbox = enqueue_inbox_message(message)
    if outbox is None:
        db.session.rollback()
        return proxy_error("站内消息同步尚未启用", 503)
    outbox.payload_json = dict(outbox.payload_json, reply_request_id=request_id)
    outbox.reply_request_key = request_key
    db.session.commit()
    return jsonify(status="confirmed", source="netdisk", message_id=int(message.id))


@infocenter_bp.route("/<surface>/<path:suffix>", methods=["GET", "HEAD", "POST"])
def proxy(surface, suffix):
    if surface not in ("desktop", "terminal"):
        return proxy_error("接口不存在", 404)
    reading = READ_DESKTOP if surface == "desktop" else READ_TERMINAL
    writing = WRITE_DESKTOP if surface == "desktop" else WRITE_TERMINAL
    permitted_read, permitted_write = bool(reading.fullmatch(suffix)), bool(writing.fullmatch(suffix))
    if not permitted_read and not permitted_write:
        return proxy_error("接口不存在", 404)
    if (request.method in ("GET", "HEAD") and not permitted_read) or (request.method == "POST" and not permitted_write):
        return proxy_error("请求方法不支持", 405)
    try:
        base, token = upstream_configuration()
    except ValueError as exc:
        return proxy_error(str(exc), 503)
    body = None
    if request.method == "POST":
        if request.content_length is not None and request.content_length > MAX_REQUEST_BYTES:
            return proxy_error("消息或附件过大", 413)
        if not request.is_json:
            return proxy_error("请使用 JSON 请求", 415)
        # Flask 3.1 added the per-request setter; Flask 3.0 is still supported by
        # this project. On 3.0 retain the host limit and always bound stream reads.
        if getattr(type(request._get_current_object()).max_content_length, "fset", None):
            request.max_content_length = MAX_REQUEST_BYTES
        body = request.stream.read(MAX_REQUEST_BYTES + 1)
        if len(body) > MAX_REQUEST_BYTES:
            return proxy_error("消息或附件过大", 413)
        try:
            if not isinstance(json.loads(body), dict):
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            return proxy_error("请求内容无效", 400)
    try:
        query = request.query_string.decode("ascii", "strict")
    except UnicodeDecodeError:
        return proxy_error("请求参数编码无效", 400)
    # No caller-controlled URL, cookie, bearer credential, or redirect is forwarded.
    if "token" in request.args or "access_token" in request.args:
        return proxy_error("请通过登录会话访问此接口", 400)
    url = base + ("/desktop/" if surface == "desktop" else "/") + suffix
    if query:
        url += "?" + query
    try:
        remote = open_upstream(url, token, body)
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            detail = json.loads(exc.read(64 * 1024))
            error_message = detail.get("error") if isinstance(detail, dict) else None
            if isinstance(error_message, dict):
                error_message = error_message.get("message")
            if not isinstance(error_message, str):
                error_message = "InfoCenter 请求未完成"
            error_message = error_message.replace(token, "[redacted]")
        except (ValueError, UnicodeDecodeError, OSError):
            error_message = "InfoCenter 请求未完成"
        finally:
            exc.close()
        if 300 <= status < 400:
            return proxy_error("InfoCenter 上游重定向被拒绝", 502)
        # Upstream authorization failure must not revoke the user's NetDisk session.
        if status in (401, 403):
            return proxy_error("InfoCenter 服务凭据无效，请联系管理员", 502)
        return proxy_error(error_message, status if 400 <= status < 500 else 502)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return proxy_error("InfoCenter 服务暂时无法连接", 502)
    headers = {name: remote.headers[name] for name in RESPONSE_HEADERS if remote.headers.get(name)}
    headers["Cache-Control"] = "no-store"
    headers["X-Content-Type-Options"] = "nosniff"
    status = remote.status
    if request.method == "HEAD":
        remote.close()
        return Response(status=status, headers=headers)
    if "json" in str(remote.headers.get("Content-Type", "")):
        try:
            data = remote.read(MAX_JSON_BYTES + 1)
            if len(data) > MAX_JSON_BYTES:
                return proxy_error("InfoCenter 响应过大", 502)
            parsed = json.loads(data)
            # Credentials stay server-side even if an upstream diagnostic echoes them.
            clean = data.decode("utf-8").replace(token, "[redacted]").encode("utf-8")
            json.loads(clean)
            if not isinstance(parsed, (dict, list)):
                return proxy_error("InfoCenter 响应格式错误", 502)
            headers.pop("Content-Length", None)
            return Response(clean, status=status, headers=headers)
        except (ValueError, UnicodeDecodeError, OSError):
            return proxy_error("InfoCenter 响应格式错误", 502)
        finally:
            remote.close()

    def chunks():
        try:
            while True:
                chunk = remote.read(128 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            remote.close()

    response = Response(stream_with_context(chunks()), status=status, headers=headers)
    response.call_on_close(remote.close)
    return response
