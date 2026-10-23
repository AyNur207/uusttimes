"""Bundled content, repeat imports, category filtering and safe updates."""

from collections import Counter
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import re

from PIL import Image

from uusttimes import create_app
from uusttimes.content import import_news, read_news
from uusttimes.models import News, User, db, utc_now

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "permanent.md"
STATIC = ROOT / "static"


class ContentTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.config = {
            "TESTING": True, "SECRET_KEY": "content-test-key", "ADMIN_EMAIL": "", "ADMIN_PASSWORD": "",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + (self.root / "content.db").as_posix(),
        }
        self.apps = []
        self.app = self.make_app()

    def make_app(self, **overrides):
        app = create_app(dict(self.config, **overrides))
        self.apps.append(app)
        return app

    def tearDown(self):
        for app in self.apps:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        self.directory.cleanup()

    def test_bundle_contains_eleven_distinct_news_and_nine_images(self):
        records = read_news(CONTENT, STATIC)
        self.assertEqual(len(records), 11)
        self.assertEqual(Counter(row["category"] for row in records), {
            "science": 2, "career": 1, "culture": 2, "study": 1, "sport": 2, "dorm": 3,
        })
        self.assertEqual(sum(row["image"] is not None for row in records), 9)
        self.assertEqual(records[0]["body"].count("Есть исследование, разработка или инженерный проект"), 1)
        self.assertNotIn("Скопировать ссылку", records[-1]["body"])
        with self.app.app_context():
            self.assertEqual(import_news(CONTENT, STATIC), (11, 0))
            articles = list(db.session.scalars(db.select(News)))
            for article in articles:
                self.assertEqual(article.status, "published")
                if article.cover_data:
                    self.assertEqual(Image.open(BytesIO(article.cover_data)).format, "WEBP")
                else:
                    self.assertIsNone(article.cover_filename)
            ids = [article.id for article in articles]
        client = self.app.test_client()
        first = client.get("/").get_data(as_text=True)
        second = client.get("/?page=2").get_data(as_text=True)
        self.assertEqual(first.count('<article class="news-card">'), 10)
        self.assertEqual(second.count('<article class="news-card">'), 1)
        for article_id in ids:
            self.assertIn(f'/news/{article_id}"', first + second)
        self.assertIn("Редакция The UUST Times", first)
        for category in {row["category"] for row in records}:
            response = client.get("/?category=" + category)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_data(as_text=True).count('<article class="news-card">'),
                             sum(row["category"] == category for row in records))
        for article_id in ids:
            self.assertEqual(client.get(f"/news/{article_id}").status_code, 200)
        self.assertEqual(client.get("/news/1/cover").mimetype, "image/webp")
        self.assertEqual(client.get("/news/7/cover").status_code, 404)
        self.assertEqual(client.get("/news/9/cover").status_code, 404)
        self.assertIn("https://vikrf.ru", client.get("/news/1").get_data(as_text=True))

    def test_startup_is_idempotent_and_keeps_publication_dates(self):
        first = self.make_app(SEED_NEWS=True)
        with first.app_context():
            before = [(item.id, item.seed_key, item.published_at) for item in db.session.scalars(db.select(News).order_by(News.id))]
        second = self.make_app(SEED_NEWS=True)
        with second.app_context():
            after = [(item.id, item.seed_key, item.published_at) for item in db.session.scalars(db.select(News).order_by(News.id))]
            self.assertEqual(before, after)
            self.assertEqual(len(after), 11)
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(User)), 1)

    def test_only_explicit_update_changes_seed_content_and_preserves_other_data(self):
        with self.app.app_context():
            import_news(CONTENT, STATIC)
            item = db.session.scalar(db.select(News).where(News.seed_key == "news-001"))
            item.title = "Заголовок изменён редактором"
            item.status = "rejected"
            item.reviewer_note = "Сохранить решение редакции"
            date = item.published_at
            manual = News(author_id=item.author_id, title="Самостоятельная новость", body="Собственный текст пользователя", status="pending", category="sport")
            db.session.add(manual)
            db.session.commit()
            self.assertEqual(import_news(CONTENT, STATIC), (0, 0))
            self.assertEqual(item.title, "Заголовок изменён редактором")
            self.assertEqual(import_news(CONTENT, STATIC, update=True), (0, 11))
            self.assertEqual(item.title, read_news(CONTENT, STATIC)[0]["title"])
            self.assertEqual(item.status, "rejected")
            self.assertEqual(item.reviewer_note, "Сохранить решение редакции")
            self.assertEqual(item.published_at, date)
            self.assertEqual(manual.body, "Собственный текст пользователя")
            self.assertEqual(manual.category, "sport")
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(News)), 12)

    def test_filter_and_pagination_keep_category_and_hide_pending(self):
        with self.app.app_context():
            author = User(email="author@example.com", password_hash="unused", role="member")
            db.session.add(author)
            db.session.flush()
            for index in range(11):
                db.session.add(News(author_id=author.id, title=f"Карьера {index}", body="Текст публикации о карьере", category="career", status="published", published_at=utc_now()))
            db.session.add(News(author_id=author.id, title="Другая тема", body="Текст о науке", category="science", status="published", published_at=utc_now()))
            db.session.add(News(author_id=author.id, title="Скрытая карьера", body="На модерации", category="career", status="pending"))
            db.session.commit()
        client = self.app.test_client()
        first = client.get("/?category=career").get_data(as_text=True)
        self.assertIn("page=2&amp;category=career", first)
        self.assertNotIn("Другая тема", first)
        self.assertNotIn("Скрытая карьера", first)
        self.assertIn("Карьера 0", client.get("/?category=career&page=2").get_data(as_text=True))
        self.assertIn("Все новости", client.get("/?category=dorm").get_data(as_text=True))
        self.assertEqual(client.get("/?category=unknown").status_code, 404)
        self.assertIn("Другая тема", client.get("/").get_data(as_text=True))

    def test_parser_rejects_bad_metadata_duplicate_ids_and_unsafe_paths(self):
        sample = "## news-001\ntitle: Заголовок новости\ncategory: study\nimage: \nlink: \n---\n\nПодробный текст новости.\n"
        path = self.root / "news.md"
        bad = (
            sample.replace("category: study", "category: unknown"),
            sample.replace("image: ", "image: ../permanent.md"),
            sample.replace("link: ", "link: javascript:alert(1)"),
            sample.replace("link: ", "link: https://example.org:99999"),
            sample + "\n" + sample,
        )
        for text in bad:
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                read_news(path, STATIC)
        with self.app.app_context():
            with self.assertRaises(ValueError):
                import_news(path, STATIC)
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(News)), 0)

    def test_bad_image_rolls_back_entire_import(self):
        static = self.root / "static"
        static.mkdir()
        (static / "invalid.png").write_bytes(b"not an image")
        path = self.root / "news.md"
        path.write_text(
            "## news-001\ntitle: Первая новость\ncategory: study\n---\nТекст первой новости.\n\n"
            "## news-002\ntitle: Вторая новость\ncategory: science\nimage: invalid.png\n---\nТекст второй новости.\n",
            encoding="utf-8",
        )
        with self.app.app_context():
            with self.assertRaises(ValueError):
                import_news(path, static)
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(News)), 0)
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(User)), 0)

    def test_cli_import_and_update(self):
        runner = self.app.test_cli_runner()
        first = runner.invoke(args=["import-news"])
        self.assertEqual(first.exit_code, 0, first.output)
        self.assertIn("Добавлено: 11", first.output)
        second = runner.invoke(args=["import-news"])
        self.assertEqual(second.exit_code, 0, second.output)
        self.assertIn("Добавлено: 0", second.output)
        updated = runner.invoke(args=["import-news", "--update"])
        self.assertEqual(updated.exit_code, 0, updated.output)
        self.assertIn("Обновлено: 11", updated.output)

    def test_deleted_seed_is_not_restored_by_restart_or_explicit_update(self):
        with self.app.app_context():
            import_news(CONTENT, STATIC)
            admin = User(email="admin@example.org", role="admin", password_hash="unused")
            db.session.add(admin)
            db.session.commit()
            admin_id = admin.id
            news_id = db.session.scalar(db.select(News.id).where(News.seed_key == "news-011"))
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(admin_id)
            session["_fresh"] = True
        detail = client.get(f"/news/{news_id}").get_data(as_text=True)
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', detail).group(1)
        result = client.post(f"/news/{news_id}/delete", data={"csrf_token": token, "confirm": "yes"})
        self.assertEqual(result.status_code, 303)
        with self.app.app_context():
            self.assertEqual(import_news(CONTENT, STATIC), (0, 0))
            self.assertEqual(import_news(CONTENT, STATIC, update=True), (0, 10))
            item = db.session.get(News, news_id)
            self.assertEqual((item.status, item.seed_key, item.body), ("deleted", "news-011", ""))
            self.assertIsNone(item.cover_data)
        restarted = self.make_app(SEED_NEWS=True)
        self.assertEqual(restarted.test_client().get(f"/news/{news_id}").status_code, 404)
        with restarted.app_context():
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(News).where(News.status == "published")), 10)
            self.assertEqual(db.session.get(News, news_id).status, "deleted")
