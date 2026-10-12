"""Read synthetic NetDisk provenance without resolving a WeChat contact shard."""

import json


def metadata(connection, uid):
    if not str(uid or "").startswith("netdisk:"):
        return None
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='netdisk_message_meta'").fetchone()
    if not exists:
        return None
    row = connection.execute("SELECT payload_json FROM netdisk_message_meta WHERE message_uid=?", (uid,)).fetchone()
    if not row:
        return None
    try:
        value = json.loads(row[0])
    except (ValueError, TypeError):
        return None
    return value if value.get("source") == "netdisk" and value.get("message_uid") == uid else None


def sender_details(payload):
    return {
        "sender_id": f"netdisk:{payload['instance_id']}:user:{int(payload.get('sender_user_id') or 0)}",
        "sender_name": payload.get("sender_name") or "Server",
        "direction": "incoming", "source": "netdisk",
    }
