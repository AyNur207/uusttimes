"""Exercise publishing, persistence, browser ownership, validation and uploads."""

from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from PIL import Image
from sqlalchemy.exc import SQLAlchemyError

from uusttimes import create_app
from uusttimes.models import News, db


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
        }
        self.apps = []
        self.app = self.make_app()
        self.client = self.app.test_client()

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
            self.assertNotEqual(news.author_token, "forged")
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

    def test_my_news_is_scoped_to_each_browser(self):
        second = self.app.test_client()
        self.publish(title="Новость первого автора")
        self.publish(second, title="Новость второго автора")
        first_html = self.client.get("/my-news").get_data(as_text=True)
        second_html = second.get("/my-news").get_data(as_text=True)
        self.assertIn("Новость первого автора", first_html)
        self.assertNotIn("Новость второго автора", first_html)
        self.assertIn("Новость второго автора", second_html)
        self.assertNotIn("Новость первого автора", second_html)
        public = second.get("/").get_data(as_text=True)
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
        with self.client.session_transaction() as session:
            author = session["author_token"]
        with self.app.app_context():
            db.session.add_all([
                News(title=f"Материал номер {i}", body="Текст университетской новости", author_token=author)
                for i in range(11)
            ])
            db.session.add(News(title="Скрытый материал", body="Не для публичной ленты", author_token=author, status="pending"))
            db.session.commit()
        first = self.client.get("/").get_data(as_text=True)
        self.assertIn("Страница 1 из 2", first)
        self.assertNotIn("Скрытый материал", first)
        self.assertIn("Материал номер 0", self.client.get("/?page=2").get_data(as_text=True))
        self.assertEqual(self.client.get("/news/12").status_code, 404)
        self.assertEqual(self.client.get("/news/12/cover").status_code, 404)
        self.assertEqual(self.client.get("/news/999").status_code, 404)
