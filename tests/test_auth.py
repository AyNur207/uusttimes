"""Real CSRF-protected registration/login/logout and administrator setup."""

import re
import unittest

from uusttimes import create_app
from uusttimes.models import User, db


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True, "SECRET_KEY": "auth-tests-only",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "ADMIN_EMAIL": "", "ADMIN_PASSWORD": "",
        })
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def token(self, path="/register"):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)

    def register(self, **changes):
        data = {
            "email": "Student@Example.com", "password": "a-test-password",
            "password2": "a-test-password", "role": "admin", "csrf_token": self.token(),
        }
        data.update(changes)
        return self.client.post("/register", data=data)

    def test_registration_hashes_password_and_never_accepts_admin_role(self):
        response = self.register()
        self.assertEqual(response.status_code, 303)
        with self.app.app_context():
            user = db.session.scalar(db.select(User))
            self.assertEqual(user.email, "student@example.com")
            self.assertEqual(user.role, "member")
            self.assertNotEqual(user.password_hash, "a-test-password")
            self.assertTrue(user.check_password("a-test-password"))
        own = self.client.get("/my-news")
        self.assertEqual(own.status_code, 200)
        self.assertIn("student@example.com", own.get_data(as_text=True))
        self.assertEqual(self.client.get("/moderation").status_code, 403)

    def logout(self):
        return self.client.post("/logout", data={"csrf_token": self.token("/my-news")})

    def test_duplicate_email_is_normalized_and_rejected(self):
        self.register()
        self.logout()
        response = self.register(email="STUDENT@example.COM")
        self.assertEqual(response.status_code, 400)
        self.assertIn("уже существует", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(User)), 1)

    def test_invalid_registration_preserves_email_and_shows_errors(self):
        for changes in ({"email": "not-email"}, {"password": "short"}, {"password2": "different"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.register(**changes).status_code, 400)
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(User)), 0)

    def test_login_logout_and_safe_return_address(self):
        self.register()
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.assertEqual(self.client.post("/logout", data={}).status_code, 400)
        self.assertEqual(self.logout().status_code, 303)
        response = self.client.post("/login?next=https://evil.example/", data={
            "email": "STUDENT@example.com", "password": "a-test-password", "csrf_token": self.token("/login"),
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], "/my-news")
        self.logout()
        response = self.client.post("/login?next=/news/new", data={
            "email": "student@example.com", "password": "a-test-password", "csrf_token": self.token("/login"),
        })
        self.assertEqual(response.headers["Location"], "/news/new")

    def test_invalid_password_and_missing_csrf_cannot_log_in(self):
        self.register()
        self.logout()
        response = self.client.post("/login", data={
            "email": "student@example.com", "password": "wrong-password", "csrf_token": self.token("/login"),
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/my-news").status_code, 302)
        self.assertEqual(self.client.post("/login", data={"email": "student@example.com", "password": "a-test-password"}).status_code, 400)
        self.assertEqual(self.client.post("/register", data={}).status_code, 400)

    def test_guests_are_sent_to_login_for_private_pages(self):
        for path in ("/my-news", "/news/new", "/submit", "/moderation"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login?next=", response.headers["Location"])

    def test_cli_can_create_and_promote_admin(self):
        self.register()
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=["create-admin", "student@example.com"])
        self.assertEqual(result.exit_code, 0, result.output)
        with self.app.app_context():
            user = db.session.scalar(db.select(User).where(User.email == "student@example.com"))
            self.assertTrue(user.is_admin)
            self.assertTrue(user.check_password("a-test-password"))
        result = runner.invoke(args=["create-admin", "newadmin@example.com"], input="test-password-123\ntest-password-123\n")
        self.assertEqual(result.exit_code, 0, result.output)
        with self.app.app_context():
            self.assertTrue(db.session.scalar(db.select(User).where(User.email == "newadmin@example.com")).is_admin)

    def test_admin_environment_bootstrap(self):
        app = create_app({
            "TESTING": True, "SECRET_KEY": "admin-tests-only", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "ADMIN_EMAIL": "BOOTSTRAP@example.com", "ADMIN_PASSWORD": "bootstrap-test-password",
        })
        with app.app_context():
            user = db.session.scalar(db.select(User))
            self.assertTrue(user.is_admin)
            self.assertEqual(user.email, "bootstrap@example.com")
            self.assertTrue(user.check_password("bootstrap-test-password"))
            db.session.remove()
            db.engine.dispose()
