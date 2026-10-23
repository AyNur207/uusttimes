"""Exercise account ownership, publishing, moderation, persistence and uploads."""

from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from PIL import Image
from sqlalchemy.exc import SQLAlchemyError

from uusttimes import create_app
from uusttimes.models import News, User, db


class FormToken(HTMLParser):
    value = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") == "csrf_token":
            self.value = attrs["value"]


def image_file():
    image = BytesIO()
    Image.new("RGB", (60, 40), color="#4d19cc").save(image, format="PNG")
    image.seek(0)
    return image


class NewsTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        root = Path(self.directory.name)
        self.config = {
            "TESTING": True, "SECRET_KEY": "news-test-key",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + (root / "news.db").as_posix(),
            "UPLOAD_FOLDER": str(root / "uploads"),
            "ADMIN_EMAIL": "", "ADMIN_PASSWORD": "",
        }
        self.apps = []
        self.app = self.make_app()
        self.client = self.app.test_client()
        with self.app.app_context():
            users = [User(email=email, role=role, password_hash="not-used-in-news-tests") for email, role in (
                ("admin@example.com", "admin"), ("second@example.com", "admin"), ("member@example.com", "member"),
            )]
            db.session.add_all(users)
            db.session.commit()
            self.admin_id, self.second_id, self.member_id = [user.id for user in users]
        self.sign_in(self.client, self.admin_id)

    def sign_in(self, client, user_id):
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True

    def make_app(self):
        app = create_app(self.config)
        self.apps.append(app)
        return app

    def tearDown(self):
        for app in self.apps:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        self.directory.cleanup()

    def token(self, client):
        response = client.get("/news/new")
        self.assertEqual(response.status_code, 200)
        parser = FormToken()
        parser.feed(response.get_data(as_text=True))
        self.assertTrue(parser.value)
        return parser.value

    def publish(self, client=None, **fields):
        client = client or self.client
        data = {
            "title": "Турнир по шахматам",
            "body": "Приглашаем студентов на открытый университетский турнир.\nУчастие бесплатное.",
            "csrf_token": self.token(client),
        }
        data.update(fields)
        response = client.post("/news/new", data=data)
        # The test client's multipart builder may spool large request bodies to disk.
        response.request.environ["wsgi.input"].close()
        return response

    def count(self):
        with self.app.app_context():
            return db.session.scalar(db.select(db.func.count()).select_from(News))

    def test_publish_appears_in_feed_detail_and_my_news(self):
        response = self.publish(
            event_at="2026-10-25T18:30", location="Корпус 1, аудитория 205",
            registration_url="https://example.org/register", status="pending", author_token="forged",
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], "/")
        with self.app.app_context():
            news = db.session.scalar(db.select(News))
            self.assertEqual(news.status, "published")
            self.assertEqual(news.author_id, self.admin_id)
            self.assertEqual(news.reviewer_id, self.admin_id)
            self.assertEqual(news.event_at.hour, 13)  # 18:30 Ufa -> 13:30 UTC
        for path in ("/", "/my-news", "/news/1"):
            html = self.client.get(path).get_data(as_text=True)
            self.assertIn("Турнир по шахматам", html)
        detail = self.client.get("/news/1").get_data(as_text=True)
        self.assertIn("25.10.2026, 18:30", detail)
        self.assertIn("https://example.org/register", detail)

    def test_records_and_ownership_survive_app_restart(self):
        self.assertEqual(self.publish().status_code, 303)
        cookie = self.client.get_cookie("session")
        restarted_app = self.make_app()
        restarted = restarted_app.test_client()
        restarted.set_cookie("session", cookie.value)
        self.assertIn("Турнир по шахматам", restarted.get("/my-news").get_data(as_text=True))
        self.assertIn("Турнир по шахматам", restarted.get("/").get_data(as_text=True))

    def test_my_news_is_scoped_to_each_account(self):
        second = self.app.test_client()
        self.sign_in(second, self.second_id)
        self.publish(title="Новость первого автора")
        self.publish(second, title="Новость второго автора")
        first_html = self.client.get("/my-news").get_data(as_text=True)
        second_html = second.get("/my-news").get_data(as_text=True)
        self.assertIn("Новость первого автора", first_html)
        self.assertNotIn("Новость второго автора", first_html)
        self.assertIn("Новость второго автора", second_html)
        self.assertNotIn("Новость первого автора", second_html)
        public = self.app.test_client().get("/").get_data(as_text=True)
        self.assertIn("Новость первого автора", public)
        self.assertIn("Новость второго автора", public)

    def test_missing_csrf_token_is_rejected(self):
        response = self.client.post("/news/new", data={"title": "Заголовок", "body": "Описание события"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.count(), 0)

    def test_invalid_fields_do_not_create_records(self):
        cases = (
            {"title": "   "}, {"title": "x" * 161}, {"body": "Коротко"},
            {"body": "x" * 20001}, {"registration_url": "javascript://example.org/alert(1)"},
            {"registration_url": "ftp://example.org/file"}, {"event_at": "not-a-date"},
            {"event_at": "0001-01-01T00:00"}, {"registration_url": "https://example.org:99999/pay"},
        )
        for fields in cases:
            with self.subTest(fields=list(fields)):
                response = self.publish(**fields)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.count(), 0)

    def test_text_is_escaped_and_line_breaks_preserved(self):
        title = '<script>alert("title")</script>'
        body = '<img src=x onerror=alert(1)>\nВторая строка новости'
        self.assertEqual(self.publish(title=title, body=body).status_code, 303)
        for path in ("/", "/my-news", "/news/1"):
            html = self.client.get(path).get_data(as_text=True)
            self.assertNotIn("<script>", html)
            self.assertNotIn("<img src=x", html)
            self.assertIn("&lt;script&gt;", html)
        self.assertIn("\nВторая строка новости", self.client.get("/news/1").get_data(as_text=True))

    def test_cover_is_reencoded_and_saved_under_generated_name(self):
        response = self.publish(cover=(image_file(), "../../original.png"))
        self.assertEqual(response.status_code, 303)
        with self.app.app_context():
            news = db.session.scalar(db.select(News))
            self.assertRegex(news.cover_filename, r"^[a-f0-9]{32}\.webp$")
            self.assertTrue((Path(self.config["UPLOAD_FOLDER"]) / news.cover_filename).is_file())
        cover = self.client.get("/news/1/cover")
        self.assertEqual(cover.status_code, 200)
        self.assertEqual(cover.mimetype, "image/webp")
        self.assertEqual(Image.open(BytesIO(cover.data)).format, "WEBP")
        cover.close()

    def test_invalid_image_and_oversized_files_are_rejected(self):
        cases = (
            (BytesIO(b"<script>not an image</script>"), "fake.jpg", 400),
            (BytesIO(b"x" * (5 * 1024 * 1024 + 1)), "large.jpg", 400),
            (BytesIO(b"x" * (6 * 1024 * 1024 + 1)), "huge.jpg", 413),
        )
        for file, filename, expected in cases:
            with self.subTest(filename=filename):
                self.assertEqual(self.publish(cover=(file, filename)).status_code, expected)
                self.assertEqual(self.count(), 0)
        self.assertEqual(list(Path(self.config["UPLOAD_FOLDER"]).glob("*")), [])

    def test_database_failure_removes_uploaded_cover(self):
        with patch.object(db.session, "commit", side_effect=SQLAlchemyError("test failure")):
            with self.assertLogs(self.app.logger, level="ERROR"):
                response = self.publish(cover=(image_file(), "cover.png"))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.count(), 0)
        self.assertEqual(list(Path(self.config["UPLOAD_FOLDER"]).glob("*")), [])

    def test_feed_pagination_and_unpublished_content(self):
        self.token(self.client)
        with self.app.app_context():
            db.session.add_all([
                News(title=f"Материал номер {i}", body="Текст университетской новости", author_id=self.admin_id, status="published")
                for i in range(11)
            ])
            db.session.add(News(title="Скрытый материал", body="Не для публичной ленты", author_id=self.member_id, status="pending"))
            db.session.commit()
        first = self.client.get("/").get_data(as_text=True)
        self.assertIn("Страница 1 из 2", first)
        self.assertNotIn("Скрытый материал", first)
        self.assertIn("Материал номер 0", self.client.get("/?page=2").get_data(as_text=True))
        guest = self.app.test_client()
        self.assertEqual(guest.get("/news/12").status_code, 404)
        self.assertEqual(guest.get("/news/12/cover").status_code, 404)
        self.assertEqual(self.client.get("/news/999").status_code, 404)

    def member_client(self):
        client = self.app.test_client()
        self.sign_in(client, self.member_id)
        return client

    def moderate(self, path, **data):
        data["csrf_token"] = self.token(self.client)
        return self.client.post(path, data=data)

    def test_member_submission_waits_for_admin_approval(self):
        member = self.member_client()
        response = self.publish(member, status="published", author_id=self.admin_id, reviewer_id=self.admin_id)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], "/my-news")
        with self.app.app_context():
            item = db.session.get(News, 1)
            self.assertEqual(item.author_id, self.member_id)
            self.assertEqual(item.status, "pending")
            self.assertIsNone(item.published_at)
            self.assertIsNone(item.reviewer_id)
        guest = self.app.test_client()
        self.assertNotIn("Турнир по шахматам", guest.get("/").get_data(as_text=True))
        self.assertIn("На проверке", member.get("/my-news").get_data(as_text=True))
        self.assertIn("Турнир по шахматам", self.client.get("/moderation").get_data(as_text=True))
        self.assertEqual(self.moderate("/moderation/1/approve").status_code, 303)
        with self.app.app_context():
            item = db.session.get(News, 1)
            self.assertEqual(item.status, "published")
            self.assertEqual(item.reviewer_id, self.admin_id)
            self.assertIsNotNone(item.published_at)
        self.assertIn("Турнир по шахматам", guest.get("/").get_data(as_text=True))
        self.assertEqual(guest.get("/news/1").status_code, 200)

    def test_unpublished_text_and_cover_only_visible_to_author_and_admin(self):
        member = self.member_client()
        self.publish(member, cover=(image_file(), "cover.png"))
        stranger = self.app.test_client()
        # An unrelated non-admin account.
        with self.app.app_context():
            user = User(email="stranger@example.com", role="member", password_hash="unused")
            db.session.add(user)
            db.session.commit()
            stranger_id = user.id
        self.sign_in(stranger, stranger_id)
        for client in (stranger, self.app.test_client()):
            self.assertEqual(client.get("/news/1").status_code, 404)
            self.assertEqual(client.get("/news/1/cover").status_code, 404)
        for client in (member, self.client):
            self.assertEqual(client.get("/news/1").status_code, 200)
            cover = client.get("/news/1/cover")
            self.assertEqual(cover.status_code, 200)
            self.assertIn("no-store", cover.headers["Cache-Control"])
            cover.close()
        self.assertIn("private", member.get("/news/1").headers["Cache-Control"])

    def test_member_cannot_moderate_or_skip_csrf(self):
        member = self.member_client()
        self.publish(member)
        self.assertEqual(member.get("/moderation").status_code, 403)
        token = self.token(member)
        for action in ("approve", "reject"):
            self.assertEqual(member.post(f"/moderation/1/{action}", data={"csrf_token": token, "reason": "Причина"}).status_code, 403)
            self.assertEqual(self.client.post(f"/moderation/1/{action}", data={}).status_code, 400)

    def test_rejection_requires_reason_and_is_visible_to_author(self):
        member = self.member_client()
        self.publish(member)
        self.moderate("/moderation/1/reject", reason=" ")
        with self.app.app_context():
            self.assertEqual(db.session.get(News, 1).status, "pending")
        self.moderate("/moderation/1/reject", reason="Уточните место проведения")
        with self.app.app_context():
            item = db.session.get(News, 1)
            self.assertEqual(item.status, "rejected")
            self.assertIsNone(item.published_at)
        own = member.get("/my-news").get_data(as_text=True)
        self.assertIn("Отклонена", own)
        self.assertIn("Уточните место проведения", own)
        self.moderate("/moderation/1/approve")
        with self.app.app_context():
            self.assertEqual(db.session.get(News, 1).status, "rejected")

    def test_images_remain_available_without_local_cache(self):
        self.publish(cover=(image_file(), "cover.png"))
        for path in Path(self.config["UPLOAD_FOLDER"]).glob("*.webp"):
            path.unlink()
        response = self.app.test_client().get("/news/1/cover")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Image.open(BytesIO(response.data)).format, "WEBP")

    def test_moderation_and_own_news_are_paginated(self):
        with self.app.app_context():
            db.session.add_all([
                News(author_id=self.member_id, title=f"Заявка {i}", body="Текст заявки на модерацию", status="pending")
                for i in range(12)
            ])
            db.session.commit()
        self.assertIn("Страница 1 из 2", self.client.get("/moderation").get_data(as_text=True))
        self.assertIn("Заявка 11", self.client.get("/moderation?page=2").get_data(as_text=True))
        member = self.member_client()
        self.assertIn("Страница 1 из 2", member.get("/my-news").get_data(as_text=True))
        self.assertIn("Страница 2 из 2", member.get("/my-news?page=999").get_data(as_text=True))
