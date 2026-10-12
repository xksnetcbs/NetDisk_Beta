"""Explicit production QA against the parent's temporary two-account fixture.

Never sends WeChat: it only creates a private thread between the QA accounts.
The parent removes reported thread/message ids together with its QA fixtures.
"""
import argparse
import datetime as dt
import http.cookiejar
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import uuid


class Client:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.token = ""
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method, path, body=None):
        headers = {"Accept": "application/json"}
        if self.token: headers["Authorization"] = "Bearer " + self.token
        data = None if body is None else json.dumps(body).encode()
        if data is not None: headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try: response = self.opener.open(request, timeout=50)
        except urllib.error.HTTPError as error: response = error
        with response:
            value = json.load(response)
            if value.get("ok") is True and isinstance(value.get("data"), dict): value = value["data"]
            return response.status, value

    def login(self, account):
        code, value = self.call("POST", "/api/auth/login", {"username": account["username"], "password": account["password"]})
        assert code == 200 and int(value["user"]["id"]) == int(account["user_id"]), "QA login failed"
        self.token = value["access_token"]


def run(fixture, instance):
    accounts = fixture["accounts"]
    assert int(accounts["super"]["user_id"]) != int(accounts["ordinary"]["user_id"]), "Need two separate QA identities"
    assert all(int(account["user_id"]) != 1 for account in accounts.values()), "Only dedicated temporary QA accounts are allowed"
    admin, ordinary = Client(fixture["url"]), Client(fixture["url"])
    created = {"thread_ids": [], "message_ids": []}
    checks = []
    try:
        admin.login(accounts["super"]); ordinary.login(accounts["ordinary"])
        marker = "DCP_NATIVE_REPLY_QA_" + uuid.uuid4().hex
        code, value = admin.call("POST", "/api/inbox/threads", {"recipients": [int(accounts["ordinary"]["user_id"])],
            "subject": "Temporary native reply QA", "content_md": marker})
        assert code == 200, "QA thread creation failed"
        thread = int(value["thread"]["id"]); created["thread_ids"].append(thread)
        code, value = ordinary.call("GET", f"/api/inbox/threads/{thread}/messages")
        assert code == 200 and len(value["items"]) == 1, "QA seed did not reach actual participant"
        original = int(value["items"][0]["id"]); created["message_ids"].append(original)
        chat, uid = f"netdisk:{instance}:thread:{thread}", f"netdisk:{instance}:inbox:{original}"
        query = urllib.parse.urlencode({"source": "netdisk", "chat_id": chat, "message_uid": uid})
        code, value = ordinary.call("GET", "/api/mobile/terminal/replies/capabilities?" + query)
        assert code == 200 and value["reply_enabled"] is True, "Ordinary current participant cannot reply"
        checks.append("ordinary_current_participant_capability")
        body = {"id": uuid.uuid4().hex, "source": "netdisk", "chat_id": chat, "message_uid": uid, "text": marker + "_reply"}
        code, value = ordinary.call("POST", "/api/mobile/terminal/replies/send", body)
        assert code == 200 and value["status"] == "confirmed", "Native reply missing confirmed ACK"
        reply_id = int(value["message_id"]); created["message_ids"].append(reply_id)
        checks.append("ordinary_native_confirmed_ack")
        code, value = ordinary.call("POST", "/api/mobile/terminal/replies/send", body)
        assert code == 200 and int(value["message_id"]) == reply_id, "Retry created a second reply"
        code, value = admin.call("GET", f"/api/inbox/threads/{thread}/messages")
        assert code == 200 and len(value["items"]) == 2 and int(value["items"][-1]["sender_id"]) == int(accounts["ordinary"]["user_id"]), "Reply sender or transaction was incorrect"
        checks.append("same_request_exactly_once_authenticated_sender")
        code, _ = ordinary.call("POST", "/api/mobile/terminal/replies/send", dict(body, text=marker+"_changed"))
        assert code == 409, "Request id payload conflict was accepted"
        code, _ = ordinary.call("POST", "/api/mobile/terminal/replies/send", dict(body, sender_id=999))
        assert code == 400, "Sender spoof was accepted"
        checks.append("payload_conflict_and_sender_spoof_rejected")
        code, _ = ordinary.call("POST", "/api/mobile/terminal/replies/send", dict(body, chat_id=chat+"wrong"))
        assert code == 403, "Forged conversation origin was accepted"
        checks.append("forged_conversation_origin_rejected")
        for target in ("ordinary-contact", "fixture@chatroom"):
            code, _ = admin.call("POST", "/api/mobile/terminal/replies/send", {"id": uuid.uuid4().hex, "source": "wechat", "chat_id": target, "text": "not sent"})
            assert code == 403, "Non-filehelper target was accepted"
        code, value = admin.call("GET", "/api/mobile/terminal/replies/capabilities?source=wechat&chat_id=filehelper")
        assert code == 200 and value["reply_enabled"] is False, "Temporary super account inherited another person's WeChat identity"
        checks.append("wechat_target_and_owner_guards_without_any_wechat_send")
        return {"generated_date": str(dt.date.today()), "summary": "Native reply production QA; temporary NetDisk conversation only, no WeChat send", "passed": checks, "cleanup": created}
    except Exception:
        # No credentials, upstream details, message contents or bearer tokens in diagnostics.
        return {"generated_date": str(dt.date.today()), "summary": "Native reply production QA failed; parent cleanup still required", "passed": checks, "cleanup": created, "failed": True}
    finally:
        for client in (admin, ordinary):
            if client.token:
                try: client.call("POST", "/api/auth/logout", {})
                except Exception: pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--instance", default="dcp-netdisk")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    result = run(json.loads(Path(args.fixture).read_text(encoding="utf-8-sig")), args.instance)
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": len(result["passed"]), "failed": result.get("failed", False), "cleanup": result["cleanup"]}))
    raise SystemExit(1 if result.get("failed") else 0)
