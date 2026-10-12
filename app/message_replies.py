"""Authenticated native quick replies: local NetDisk and the owner's filehelper."""
import json
import re
import urllib.error

from flask import current_app, jsonify, request

from .extensions import db
from .infocenter import MAX_JSON_BYTES, lock_reply_actor, netdisk_reply_target, open_upstream, send_netdisk_reply, upstream_configuration


def is_wechat_owner(user):
    owner = current_app.config.get("MESSAGE_BRIDGE_TERMINAL_USER_ID")
    return user.role_system == "super_admin" and owner is not None and str(owner) == str(user.id)


def _remote(action, body=None, method="GET"):
    base, token = upstream_configuration()
    remote = open_upstream(base + "/desktop/send/" + action, token,
                           json.dumps(body).encode() if body is not None else None, method=method)
    try:
        data = remote.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES:
            raise ValueError("Invalid sender response")
        value = json.loads(data.decode("utf-8").replace(token, "[redacted]"))
        if not isinstance(value, dict):
            raise ValueError("Invalid sender response")
        return value
    finally:
        remote.close()


def register_reply_routes(bp):
    @bp.get("/replies/capabilities")
    def reply_capabilities():
        user = lock_reply_actor()
        source, chat, uid = request.args.get("source"), request.args.get("chat_id"), request.args.get("message_uid")
        if source == "netdisk":
            _thread, _project, error = netdisk_reply_target(chat, uid, user)
            if error:
                return jsonify(reply_enabled=False, source=source, reason=error[0].get_json().get("error")), 200, {"Cache-Control": "no-store"}
            return jsonify(reply_enabled=True, source=source, chat_id=chat, target_label="NetDisk 站内会话"), 200, {"Cache-Control": "no-store"}
        if source != "wechat" or chat != "filehelper" or not is_wechat_owner(user):
            return jsonify(reply_enabled=False, reason="仅支持当前网盘会话或本人的文件传输助手"), 200, {"Cache-Control": "no-store"}
        # Never hold account/session locks during the read-only availability probe.
        db.session.rollback()
        try:
            ready = _remote("capabilities").get("available") is True
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            ready = False
        user = lock_reply_actor()
        ready = ready and is_wechat_owner(user)
        return jsonify(reply_enabled=ready, source="wechat", chat_id="filehelper", target_label="文件传输助手",
                       reason="" if ready else "微信发送服务暂未就绪"), 200, {"Cache-Control": "no-store"}

    @bp.post("/replies/send")
    def reply_send():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) - {"source", "chat_id", "message_uid", "text", "id"}:
            return jsonify(error="回复请求无效"), 400
        source, chat = body.get("source"), body.get("chat_id")
        if source == "netdisk":
            return send_netdisk_reply(chat)
        if source != "wechat" or chat != "filehelper":
            return jsonify(error="微信快捷回复只支持本人的文件传输助手"), 403
        text, key = body.get("text"), body.get("id")
        if not isinstance(text, str) or not text.strip() or len(text) > 4000 or "\x00" in text:
            return jsonify(error="请输入 1 至 4000 字的回复"), 400
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", key):
            return jsonify(error="发送请求编号无效"), 400
        user = lock_reply_actor()
        if not is_wechat_owner(user):
            return jsonify(error="此账号不是当前微信账号的所有者"), 403
        # The private sender persists the receipt before its send key. Replaying
        # the same id returns that receipt and never presses send a second time.
        db.session.commit()
        try:
            result = _remote("prepare", {"id": key, "chat": "filehelper", "text": text}, method="POST")
            status = result.get("status")
            if status not in ("confirmed", "submitted", "uncertain"):
                return jsonify(error="微信尚未接受发送，请检查服务后重试", status=status or "unavailable"), 502
            return jsonify(status=status, source="wechat", id=key, chat_id="filehelper"), 200, {"Cache-Control": "no-store"}
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            return jsonify(error="发送结果未确认，请用同一请求检查状态，不要重复发送", status="uncertain", id=key), 502

    @bp.get("/replies/<key>/status")
    def reply_status(key):
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", key):
            return jsonify(error="发送请求编号无效"), 400
        user = lock_reply_actor()
        if not is_wechat_owner(user):
            return jsonify(error="此账号不能查看微信发送状态"), 403
        db.session.rollback()
        try:
            result = _remote("status", {"id": key}, method="POST")
            user = lock_reply_actor()
            if not is_wechat_owner(user):
                return jsonify(error="此账号不能查看微信发送状态"), 403
            return jsonify(status=result.get("status", "uncertain"), source="wechat", id=key), 200, {"Cache-Control": "no-store"}
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            return jsonify(error="暂时无法确认发送结果，请稍后检查", status="uncertain", id=key), 502
