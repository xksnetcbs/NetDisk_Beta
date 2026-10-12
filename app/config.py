import os
import datetime as dt
import json


class Config:
    SECRET_KEY = ""
    JWT_SECRET_KEY = ""
    SQLALCHEMY_DATABASE_URI = None
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TOKEN_EXPIRES_MIN = 120
    JWT_ACCESS_TOKEN_EXPIRES = dt.timedelta(minutes=int(TOKEN_EXPIRES_MIN))

    STORAGE_ROOT = os.path.abspath("./storage")
    SPECIAL_STORAGE_USERNAME = "storage_admin"
    SPECIAL_STORAGE_ROOT = "~/Net_Disk"
    AUTH_SESSION_DAYS = 30
    AUTH_SESSION_COOKIE_SECURE = None
    AUTH_SESSION_COOKIE_SAMESITE = "Lax"
    READABLE_STORAGE_ENABLED = True
    READABLE_HISTORY_ROOT = None
    INFOCENTER_API_BASE = ""
    INFOCENTER_API_TOKEN = ""
    INFOCENTER_TIMEOUT = 45
    TERMINAL_CALENDAR_URL = ""
    TERMINAL_CALENDAR_BASIC = ""
    MESSAGE_BRIDGE_ENABLED = False
    MESSAGE_BRIDGE_INLINE_DELIVERY = False
    MESSAGE_BRIDGE_CAPTURE_DB = ""
    MESSAGE_BRIDGE_TERMINAL_DB = ""
    MESSAGE_BRIDGE_INSTANCE_ID = "dcp-netdisk"
    MESSAGE_BRIDGE_TERMINAL_USER_ID = None
    WECHAT_FILES_ENABLED = False
    WECHAT_FILES_CAPTURE_DB = ""
    WECHAT_FILES_SOURCE_ROOT = ""
    WECHAT_FILES_MEDIA_ROOT = ""
    WECHAT_FILES_INSTANCE_ID = "linux-wechat"
    WECHAT_FILES_PROJECT_KEY = "WECHAT_FILES"
    MAX_UPLOAD_MB = 200
    FRONTEND_ORIGIN = "http://localhost:5105"


def load_config():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    candidates = [
        os.environ.get("NETDISK_CONFIG", ""),
        os.path.join(root_dir, "config.local.json"),
        os.path.join(root_dir, "config.json"),
        "/etc/dcp_netdisk/config.json",
        "/etc/netdisk_beta/config.json",
    ]
    data = None
    for p in candidates:
        try:
            if os.path.exists(p) and os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                break
        except Exception:
            data = None

    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(k, str) and k.isupper():
                setattr(Config, k, v)

    Config.JWT_ACCESS_TOKEN_EXPIRES = dt.timedelta(minutes=int(getattr(Config, "TOKEN_EXPIRES_MIN", 120) or 120))

    if not getattr(Config, "SQLALCHEMY_DATABASE_URI", None):
        raise RuntimeError("SQLALCHEMY_DATABASE_URI is required. Put it in config.local.json or /etc/dcp_netdisk/config.json")
    for key in ("SECRET_KEY", "JWT_SECRET_KEY"):
        value = str(getattr(Config, key, "") or "")
        if len(value) < 32 or value.startswith("REPLACE_"):
            raise RuntimeError(key + " must be configured with a private random value of at least 32 characters")
    return Config
