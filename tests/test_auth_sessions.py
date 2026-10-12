"""Authentication integration tests; uses only a disposable in-memory database."""

import datetime as dt
import unittest

from flask import Flask
from flask_jwt_extended import create_access_token
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles

from app.api import api_bp
from app.auth_sessions import COOKIE_NAME, register_auth_callbacks
from app.extensions import db, jwt
from app.models import AuthRefreshToken, User, UserSettings, utcnow
from app.services import hash_password


@compiles(BigInteger, "sqlite")
def sqlite_bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


class AuthSessionTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite://",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            JWT_SECRET_KEY="disposable-auth-test-secret-at-least-32-characters",
            JWT_ACCESS_TOKEN_EXPIRES=dt.timedelta(minutes=120),
            AUTH_SESSION_DAYS=30,
        )
        db.init_app(self.app)
        jwt.init_app(self.app)
        register_auth_callbacks(jwt)
        self.app.register_blueprint(api_bp, url_prefix="/api")
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        password_hash = hash_password("test-password")
        for user_id, name, role in [(1, "member", "user"), (2, "admin", "super_admin")]:
            db.session.add(User(
                id=user_id, username=name, display_name=name,
                password_hash=password_hash, role_system=role,
                status="active", is_activated=True,
            ))
            db.session.add(UserSettings(user_id=user_id))
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def login(self, client=None, name="member", password="test-password"):
        response = (client or self.client).post("/api/auth/login", json={"username": name, "password": password})
        self.assertEqual(response.status_code, 200)
        return response.json["data"]["access_token"]

    def refresh(self, client=None):
        return (client or self.client).post("/api/auth/refresh", headers={"X-DCP-Session": "1"})

    def me(self, token, client=None):
        return (client or self.client).get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    def test_login_cookie_survives_next_visit_without_local_access_token(self):
        self.login()
        cookie = self.client.get_cookie(COOKIE_NAME, path="/api/auth")
        self.assertTrue(cookie.http_only)
        self.assertEqual(cookie.same_site, "Lax")
        self.assertIsNotNone(cookie.expires)
        next_visit = self.app.test_client()
        next_visit.set_cookie(COOKIE_NAME, cookie.value, path="/api/auth")
        response = self.refresh(next_visit)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["user"]["username"], "member")
        self.assertEqual(self.me(response.json["data"]["access_token"], next_visit).status_code, 200)
        self.assertNotEqual(AuthRefreshToken.query.one().token_hash, cookie.value)

    def test_expired_access_token_can_be_recovered_with_cookie(self):
        self.login()
        row = AuthRefreshToken.query.one()
        expired = create_access_token(identity="1", additional_claims={"auth_session": str(row.id)}, expires_delta=dt.timedelta(seconds=-1))
        self.assertEqual(self.me(expired).status_code, 401)
        response = self.refresh()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.me(response.json["data"]["access_token"]).status_code, 200)

    def test_refresh_slides_expiry_and_keeps_secret_for_parallel_tabs(self):
        self.login()
        cookie_value = self.client.get_cookie(COOKIE_NAME, path="/api/auth").value
        row = AuthRefreshToken.query.one()
        row.expires_at = utcnow() + dt.timedelta(days=1)
        db.session.commit()
        self.assertEqual(self.refresh().status_code, 200)
        self.assertEqual(self.refresh().status_code, 200)
        self.assertEqual(self.client.get_cookie(COOKIE_NAME, path="/api/auth").value, cookie_value)
        self.assertGreater(row.expires_at.replace(tzinfo=dt.timezone.utc), utcnow() + dt.timedelta(days=29))

    def test_logout_revokes_this_device_without_revoking_other_device(self):
        token = self.login()
        other_device = self.app.test_client()
        other_token = self.login(other_device)
        response = self.client.post("/api/auth/logout", headers={"X-DCP-Session": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.get_cookie(COOKIE_NAME, path="/api/auth"))
        self.assertEqual(self.refresh().status_code, 401)
        self.assertEqual(self.me(token).status_code, 401)
        self.assertEqual(self.me(other_token, other_device).status_code, 200)
        self.assertEqual(self.refresh(other_device).status_code, 200)

    def test_password_change_revokes_all_devices(self):
        token = self.login()
        other_device = self.app.test_client()
        other_token = self.login(other_device)
        response = self.client.post("/api/auth/change-password", headers={"Authorization": f"Bearer {token}"}, json={"old_password": "test-password", "new_password": "changed-password"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.me(token).status_code, 401)
        self.assertEqual(self.me(other_token, other_device).status_code, 401)
        self.assertEqual(self.refresh(other_device).status_code, 401)
        self.assertIsNone(self.client.get_cookie(COOKIE_NAME, path="/api/auth"))
        self.assertTrue(self.login(password="changed-password"))

    def test_disabled_then_enabled_account_cannot_reuse_old_session(self):
        token = self.login()
        admin_client = self.app.test_client()
        admin_token = self.login(admin_client, name="admin")
        headers = {"Authorization": f"Bearer {admin_token}"}
        self.assertEqual(admin_client.post("/api/admin/users/1/disable", headers=headers).status_code, 200)
        self.assertEqual(self.me(token).status_code, 401)
        self.assertEqual(admin_client.post("/api/admin/users/1/enable", headers=headers).status_code, 200)
        self.assertEqual(self.me(token).status_code, 401)
        self.assertEqual(self.refresh().status_code, 401)

    def test_unactivation_revokes_session(self):
        token = self.login()
        admin_client = self.app.test_client()
        admin_token = self.login(admin_client, name="admin")
        response = admin_client.patch("/api/users/1", headers={"Authorization": f"Bearer {admin_token}"}, json={"is_activated": False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.me(token).status_code, 401)
        self.assertEqual(self.refresh().status_code, 401)

    def test_cookie_post_requires_custom_header(self):
        token = self.login()
        self.assertEqual(self.client.post("/api/auth/refresh").status_code, 403)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 403)
        self.assertEqual(self.me(token).status_code, 200)

    def test_session_expiry_clears_cookie_and_rejects_access(self):
        token = self.login()
        row = AuthRefreshToken.query.one()
        row.expires_at = utcnow() - dt.timedelta(seconds=1)
        db.session.commit()
        self.assertEqual(self.me(token).status_code, 401)
        self.assertEqual(self.refresh().status_code, 401)
        self.assertIsNone(self.client.get_cookie(COOKIE_NAME, path="/api/auth"))

    def test_failed_login_creates_no_session(self):
        response = self.client.post("/api/auth/login", json={"username": "member", "password": "wrong-password"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(AuthRefreshToken.query.count(), 0)

    def test_still_valid_legacy_token_receives_persistent_session(self):
        legacy_token = create_access_token(identity="1")
        response = self.me(legacy_token)
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.json["data"])
        self.assertIsNotNone(self.client.get_cookie(COOKIE_NAME, path="/api/auth"))
        self.assertEqual(self.refresh().status_code, 200)

    def test_legacy_token_cannot_recreate_session_after_logout(self):
        legacy_token = create_access_token(identity="1")
        self.assertEqual(self.me(legacy_token).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout", headers={"X-DCP-Session": "1"}).status_code, 200)
        self.assertEqual(self.me(legacy_token).status_code, 401)

    def test_disable_and_enable_revoke_legacy_token_without_device_session(self):
        legacy_token = create_access_token(identity="1")
        admin_client = self.app.test_client()
        admin_token = self.login(admin_client, name="admin")
        headers = {"Authorization": f"Bearer {admin_token}"}
        self.assertEqual(admin_client.post("/api/admin/users/1/disable", headers=headers).status_code, 200)
        self.assertEqual(admin_client.post("/api/admin/users/1/enable", headers=headers).status_code, 200)
        self.assertEqual(self.me(legacy_token).status_code, 401)


if __name__ == "__main__":
    unittest.main()
