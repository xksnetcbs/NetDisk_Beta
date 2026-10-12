"""Per-user Terminal schedules and role-gated access to the existing services."""

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from sqlalchemy import or_

from .extensions import db
from .infocenter import MAX_JSON_BYTES, NoRedirect, open_upstream, upstream_configuration
from .models import User
from .schedules import assemble_schedules, milliseconds, own_schedules as netdisk_schedules, register_schedule_routes
from .message_replies import register_reply_routes


mobile_bp = Blueprint("mobile_terminal", __name__)
READ_PATHS = re.compile(r"(?:health|messages|stream|attention|directory|desktop/messages|timetable|llm|schedules|unread)\Z")
WRITE_PATHS = re.compile(r"(?:messages/[0-9]+/read|messages/read-all|messages/[0-9]+/process|conversations/(?:summary|read)|directory/[^/\x00-\x1f]+|schedules/[A-Za-z0-9_-]+|attention|attention/[A-Za-z0-9_.@:-]+|attention/summary|timetable|llm|llm/test|llm/process|summarize|test-notification)\Z")


def current_mobile_user():
    return db.session.get(User, int(get_jwt_identity()))


@mobile_bp.before_request
def require_login():
    if request.method == "OPTIONS":
        return
    verify_jwt_in_request()
    user = current_mobile_user()
    if not user or user.status != "active" or not user.is_activated:
        return jsonify(error="账号不可登录"), 403


def _snapshot_from_terminal():
    base, token = upstream_configuration()
    remote = open_upstream(base + "/snapshot", token)
    try:
        data = remote.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES:
            raise ValueError("snapshot too large")
        result = json.loads(data.decode("utf-8").replace(token, "[redacted]"))
        if not isinstance(result, dict):
            raise ValueError("invalid snapshot")
        return result
    finally:
        remote.close()


@mobile_bp.get("/snapshot")
def snapshot():
    user = current_mobile_user()
    access = user.role_system == "super_admin"
    result = {"messages": [], "schedules": [], "revision": 0, "cursor": 0, "unread": 0, "llm": {}}
    if access:
        try:
            result = _snapshot_from_terminal()
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            result["upstream_unavailable"] = True
    schedules, flags, own_count = assemble_schedules(user, result if access else None)
    result.update(terminal_access=access, netdisk_user_id=int(user.id),
                  schedules=schedules, netdisk_schedule_count=own_count, **flags)
    if not access:
        result["messages"] = []
        result["unread"] = 0
    return jsonify(result), 200, {"Cache-Control": "no-store"}


@mobile_bp.get("/calendar")
def calendar_feed():
    if current_mobile_user().role_system != "super_admin":
        return jsonify(error="只有超级管理员可以访问共享课表"), 403
    url = current_app.config.get("TERMINAL_CALENDAR_URL", "")
    credential = current_app.config.get("TERMINAL_CALENDAR_BASIC", "")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not credential:
        return jsonify(error="课表服务未配置"), 503
    try:
        opener = urllib.request.build_opener(NoRedirect)
        remote = opener.open(urllib.request.Request(url, headers={"Authorization": "Basic " + credential, "Accept": "text/calendar"}), timeout=current_app.config.get("INFOCENTER_TIMEOUT", 45))
        try:
            data = remote.read(MAX_JSON_BYTES + 1)
            if len(data) > MAX_JSON_BYTES or not data.lstrip().startswith(b"BEGIN:VCALENDAR"):
                return jsonify(error="课表响应无效"), 502
            return Response(data, content_type="text/calendar; charset=utf-8", headers={"Cache-Control": "no-store"})
        finally:
            remote.close()
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return jsonify(error="课表服务暂时无法连接"), 502


@mobile_bp.delete("/calendar/<uid>")
def calendar_delete(uid):
    if current_mobile_user().role_system != "super_admin":
        return jsonify(error="只有超级管理员可以修改共享课表"), 403
    if not re.fullmatch(r"phone-[A-Za-z0-9_-]{1,128}", uid):
        return jsonify(error="只能删除手机创建的日程"), 400
    url = current_app.config.get("TERMINAL_CALENDAR_URL", "")
    credential = current_app.config.get("TERMINAL_CALENDAR_BASIC", "")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not credential:
        return jsonify(error="课表服务未配置"), 503
    try:
        opener = urllib.request.build_opener(NoRedirect)
        remote = opener.open(urllib.request.Request(url.rstrip("/") + "/" + urllib.parse.quote(uid, safe="") + ".ics", method="DELETE", headers={"Authorization": "Basic " + credential}), timeout=current_app.config.get("INFOCENTER_TIMEOUT", 45))
        remote.close()
        return jsonify(ok=True), 200, {"Cache-Control": "no-store"}
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return jsonify(error="日程删除未完成"), 502


@mobile_bp.route("/<path:path>", methods=["GET", "POST", "PATCH", "DELETE"])
def terminal_proxy(path):
    if current_mobile_user().role_system != "super_admin":
        return jsonify(error="只有超级管理员可以访问微信与共享终端数据"), 403
    permitted = READ_PATHS if request.method == "GET" else WRITE_PATHS
    if not permitted.fullmatch(path):
        return jsonify(error="接口不存在"), 404
    if "token" in request.args or "access_token" in request.args:
        return jsonify(error="不支持URL中的凭据"), 400
    try:
        base, token = upstream_configuration()
        body = None
        if request.method != "GET":
            if not request.is_json:
                return jsonify(error="请使用JSON请求"), 415
            body = request.get_data()
            if len(body) > 1024 * 1024:
                return jsonify(error="请求过大"), 413
            if not isinstance(json.loads(body), dict):
                return jsonify(error="请求内容无效"), 400
        url = base + "/" + path
        if request.query_string:
            url += "?" + request.query_string.decode("ascii")
        remote = open_upstream(url, token, body)
    except ValueError:
        return jsonify(error="终端服务配置或请求内容无效"), 503
    except urllib.error.HTTPError as error:
        status = 502 if error.code in (401, 403) or error.code >= 500 or error.code < 400 else error.code
        error.close()
        return jsonify(error="终端请求未完成"), status
    except (urllib.error.URLError, OSError, TimeoutError):
        return jsonify(error="终端服务暂时无法连接"), 502
    content_type = remote.headers.get("Content-Type", "application/json")
    if "event-stream" not in content_type:
        try:
            data = remote.read(MAX_JSON_BYTES + 1)
            if len(data) > MAX_JSON_BYTES:
                return jsonify(error="终端响应过大"), 502
            return Response(data.decode("utf-8").replace(token, "[redacted]"), status=remote.status,
                            content_type=content_type, headers={"Cache-Control": "no-store"})
        finally:
            remote.close()

    def stream():
        try:
            while True:
                line = remote.readline()
                if not line:
                    break
                # A long-lived stream must stop when this account loses access.
                # End the read transaction so MySQL sees revocation/role changes.
                try:
                    db.session.rollback()
                    verify_jwt_in_request()
                    user = current_mobile_user()
                    if not user or user.status != "active" or not user.is_activated or user.role_system != "super_admin":
                        break
                except Exception:
                    break
                yield line.replace(token.encode("utf-8"), b"[redacted]")
        finally:
            remote.close()
    return Response(stream_with_context(stream()), content_type=content_type,
                    headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


register_schedule_routes(mobile_bp)
register_reply_routes(mobile_bp)
