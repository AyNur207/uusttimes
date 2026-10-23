import sqlite3
from contextlib import closing
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateColumn
from werkzeug.security import generate_password_hash

from uusttimes import _database_uri, create_app
from uusttimes.models import News, User, db


class SchemaTests(TestCase):
    def test_existing_emil_database_is_upgraded_without_data_loss(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "existing.sqlite3"
            password_hash = generate_password_hash("existing-user-password")
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript('''
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY, email VARCHAR(255) UNIQUE NOT NULL,
                        password_hash VARCHAR(255) NOT NULL, role VARCHAR(20) NOT NULL,
                        created_at DATETIME NOT NULL
                    );
                    CREATE TABLE news_items (
                        id INTEGER PRIMARY KEY, title VARCHAR(200) NOT NULL, body TEXT NOT NULL,
                        status VARCHAR(20) NOT NULL, author_id INTEGER NOT NULL,
                        reviewer_id INTEGER, created_at DATETIME NOT NULL, reviewed_at DATETIME,
                        FOREIGN KEY(author_id) REFERENCES users(id), FOREIGN KEY(reviewer_id) REFERENCES users(id)
                    );
                ''')
                connection.execute("INSERT INTO users VALUES (7, ?, ?, 'admin', '2026-10-21 10:00:00')", ("existing@example.com", password_hash))
                connection.execute("INSERT INTO news_items VALUES (9, ?, ?, 'approved', 7, 7, '2026-10-21 11:00:00', '2026-10-22 12:00:00')", ("Существующая новость", "Полный текст существующей новости"))
                connection.execute("INSERT INTO news_items VALUES (10, ?, ?, 'pending', 7, NULL, '2026-10-22 13:00:00', NULL)", ("На проверке", "Неопубликованная существующая новость"))
                connection.commit()
            config = {
                "TESTING": True, "SECRET_KEY": "migration-tests-only",
                "SQLALCHEMY_DATABASE_URI": "sqlite:///" + path.as_posix(),
                "ADMIN_EMAIL": "", "ADMIN_PASSWORD": "",
            }
            for _ in range(2):
                app = create_app(config)
                with app.app_context():
                    user = db.session.get(User, 7)
                    self.assertEqual(user.password_hash, password_hash)
                    self.assertTrue(user.check_password("existing-user-password"))
                    item = db.session.get(News, 9)
                    self.assertEqual(item.title, "Существующая новость")
                    self.assertEqual(item.status, "published")
                    self.assertEqual(item.author_id, 7)
                    self.assertEqual(item.reviewer_id, 7)
                    self.assertEqual(item.published_at.day, 22)
                    self.assertEqual(db.session.get(News, 10).status, "pending")
                    self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(News)), 2)
                self.assertEqual(app.test_client().get("/").status_code, 200)
                self.assertEqual(app.test_client().get("/news/10").status_code, 404)
                with app.app_context():
                    db.session.remove()
                    db.engine.dispose()
            client = app.test_client()
            with client.session_transaction() as session:
                session["_user_id"] = "7"
                session["_fresh"] = True
            form_html = client.get("/news/new").get_data(as_text=True)
            token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', form_html).group(1)
            response = client.post("/news/new", data={
                "csrf_token": token, "title": "Новая публикация после обновления",
                "body": "Текст новой публикации после обновления схемы.", "location": "Уфа",
            })
            self.assertEqual(response.status_code, 303)
            with app.app_context():
                self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(News)), 3)
                db.session.remove()
                db.engine.dispose()
            with closing(sqlite3.connect(path)) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(news_items)")}
                self.assertTrue({"cover_data", "cover_filename", "published_at", "reviewer_note", "event_at", "location", "registration_url", "category", "seed_key", "external_url"} <= columns)
                self.assertEqual(connection.execute("SELECT category FROM news_items WHERE id = 9").fetchone()[0], "study")

    def test_postgres_urls_choose_installed_psycopg_driver(self):
        for value in ("postgres://user:password@host/database", "postgresql://user:password@host/database"):
            self.assertEqual(_database_uri(value), "postgresql+psycopg://user:password@host/database")
        self.assertEqual(_database_uri(None), "sqlite:///uusttimes.sqlite3")
        self.assertEqual(_database_uri("sqlite:///custom.db"), "sqlite:///custom.db")
        definition = str(CreateColumn(News.__table__.c.cover_data).compile(dialect=postgresql.dialect()))
        self.assertIn("BYTEA", definition)
