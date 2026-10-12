"""Persistent browser sessions backed by the existing refresh-token table."""

import datetime as dt
import hashlib
import secrets

from flask import current_app, make_response, request
from flask_jwt_extended import create_access_token

from .extensions import db
from .models import AuthRefreshToken, User, utcnow


COOKIE_NAME = "dcp_netdisk_session"
COOKIE_PATH = "/api/auth"


def session_duration():
    return dt.timedelta(days=int(current_app.config.get("AUTH_SESSION_DAYS", 30)))


def token_hash(raw_token):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def as_utc(value):
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value


def is_live_session(session):
    return bool(session and session.revoked_at is None and as_utc(session.expires_at) > utcnow())


def cookie_session():
    raw_token = request.cookies.get(COOKIE_NAME, "")
    if not raw_token or len(raw_token) > 256:
        return None, None
    session = AuthRefreshToken.query.filter_by(token_hash=token_hash(raw_token)).first()
    return session, raw_token


def revoke_user_sessions(user_id):
    now = utcnow()
    AuthRefreshToken.query.filter_by(user_id=int(user_id), revoked_at=None).update(
        {"revoked_at": now}, synchronize_session="fetch"
    )
    # Retain a cutoff for JWTs issued before persistent sessions were introduced.
    # Otherwise a still-valid old JWT could recreate a session after a password reset.
    cutoff_key = f"legacy-revoked:{int(user_id)}"
    cutoff = AuthRefreshToken.query.filter_by(token_hash=cutoff_key).first()
    if not cutoff:
        cutoff = AuthRefreshToken(user_id=int(user_id), token_hash=cutoff_key)
        db.session.add(cutoff)
    cutoff.revoked_at = now
    cutoff.expires_at = now + session_duration()


def create_device_session(user_id):
    previous, _ = cookie_session()
    if previous and previous.revoked_at is None:
        previous.revoked_at = utcnow()
    raw_token = secrets.token_urlsafe(48)
    session = AuthRefreshToken(
        user_id=int(user_id), token_hash=token_hash(raw_token),
        expires_at=utcnow() + session_duration(), revoked_at=None,
    )
    db.session.add(session)
    db.session.flush()
    return session, raw_token


def access_token_for(session):
    return create_access_token(
        identity=str(session.user_id), additional_claims={"auth_session": str(session.id)}
    )


def cookie_options():
    secure = current_app.config.get("AUTH_SESSION_COOKIE_SECURE")
    return {
        "httponly": True,
        "secure": request.is_secure if secure is None else bool(secure),
        "samesite": current_app.config.get("AUTH_SESSION_COOKIE_SAMESITE", "Lax"),
        "path": COOKIE_PATH,
    }


def session_response(data, raw_token=None, clear=False, status=200):
    response = make_response(data, status)
    response.headers["Cache-Control"] = "no-store"
    if clear:
        response.delete_cookie(COOKIE_NAME, **cookie_options())
    elif raw_token:
        response.set_cookie(
            COOKIE_NAME, raw_token, max_age=int(session_duration().total_seconds()),
            **cookie_options(),
        )
    return response


def validate_access_claims(payload):
    """Also used by preview URLs, which decode a bearer token manually."""
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        return False
    user = db.session.get(User, user_id)
    if not user or user.status != "active" or not user.is_activated:
        return False
    session_id = payload.get("auth_session")
    # A still-valid pre-upgrade token can obtain its first cookie through /auth/me.
    if session_id is None:
        issued_at = payload.get("iat")
        if not isinstance(issued_at, (int, float)):
            return False
        latest_revoke = (
            AuthRefreshToken.query.filter(
                AuthRefreshToken.user_id == user_id,
                AuthRefreshToken.revoked_at.isnot(None),
            ).order_by(AuthRefreshToken.revoked_at.desc()).first()
        )
        if latest_revoke and issued_at <= as_utc(latest_revoke.revoked_at).timestamp():
            return False
        return True
    try:
        session = db.session.get(AuthRefreshToken, int(session_id))
    except (TypeError, ValueError):
        return False
    return is_live_session(session) and int(session.user_id) == user_id


def register_auth_callbacks(jwt):
    @jwt.token_in_blocklist_loader
    def token_revoked(_header, payload):
        return not validate_access_claims(payload)

    @jwt.revoked_token_loader
    def revoked_token(_header, _payload):
        return {"ok": False, "error": {"code": "SESSION_REVOKED", "message": "登录已失效，请重新登录"}}, 401
