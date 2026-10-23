from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from uusttimes import create_app
from uusttimes.models import News, NewsReaction, User, db, utc_now
from uusttimes.reaction_types import REACTIONS


class TokenParser(HTMLParser):
    value = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") == "csrf_token":
            self.value = attrs["value"]


class ReactionTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        path = Path(self.directory.name) / "reactions.db"
        self.config = {
            "TESTING": True, "SECRET_KEY": "reaction-test-key",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + path.as_posix(),
            "ADMIN_EMAIL": "", "ADMIN_PASSWORD": "",
        }
        self.app = create_app(self.config)
        self.apps = [self.app]
        with self.app.app_context():
            users = [User(email=f"{role}{index}@example.org", role=role, password_hash="unused")
                     for index, role in enumerate(("member", "member", "admin"), 1)]
            db.session.add_all(users)
            db.session.flush()
            self.first_id, self.second_id, self.admin_id = [user.id for user in users]
            items = [News(author_id=self.first_id, title=f"Новость {index}", body="Подробный текст новости", category="science",
                          status=status, published_at=utc_now() if status == "published" else None)
                     for index, status in enumerate(("published", "published", "pending", "rejected"), 1)]
            db.session.add_all(items)
            db.session.commit()
            self.first_news, self.second_news, self.pending_news, self.rejected_news = [item.id for item in items]
        self.client = self.signed_client(self.first_id)

    def tearDown(self):
        for app in self.apps:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        self.directory.cleanup()

    def signed_client(self, user_id, app=None):
        client = (app or self.app).test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def token(self, client):
        parser = TokenParser()
        parser.feed(client.get(f"/news/{self.first_news}").get_data(as_text=True))
        if parser.value is None:
            parser.feed(client.get("/login").get_data(as_text=True))
        self.assertTrue(parser.value)
        return parser.value

    def react(self, kind="like", client=None, news_id=None, json=True, **fields):
        client = client or self.client
        data = {"csrf_token": self.token(client), "reaction": kind, **fields}
        return client.post(f"/news/{news_id or self.first_news}/reaction", data=data,
                           headers={"Accept": "application/json"} if json else {})

    def rows(self):
        with self.app.app_context():
            return [(row.news_id, row.user_id, row.kind) for row in db.session.scalars(db.select(NewsReaction))]

    def test_select_change_and_remove_one_reaction(self):
        result = self.react("like")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["selected"], "like")
        self.assertEqual(result.json["counts"], dict.fromkeys(REACTIONS, 0) | {"like": 1})
        result = self.react("fire")
        self.assertEqual(result.json["selected"], "fire")
        self.assertEqual(result.json["counts"]["like"], 0)
        self.assertEqual(result.json["counts"]["fire"], 1)
        self.assertEqual(self.rows(), [(self.first_news, self.first_id, "fire")])
        result = self.react("fire")
        self.assertIsNone(result.json["selected"])
        self.assertEqual(sum(result.json["counts"].values()), 0)
        self.assertEqual(self.rows(), [])

    def test_all_allowed_emoji_and_invalid_codes(self):
        for code in REACTIONS:
            result = self.react(code)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json["selected"], code)
            self.assertEqual(len(self.rows()), 1)
        before = self.rows()
        for code in ("", "other", "<script>alert(1)</script>", "👍"):
            self.assertEqual(self.react(code).status_code, 400)
            self.assertEqual(self.rows(), before)

    def test_accounts_and_news_have_independent_reactions(self):
        second = self.signed_client(self.second_id)
        self.react("love", user_id=self.second_id, news_id=self.first_news)
        result = self.react("love", client=second)
        self.assertEqual(result.json["counts"]["love"], 2)
        self.react("sad", news_id=self.second_news)
        result = self.react("wow", client=second)
        self.assertEqual(result.json["counts"]["love"], 1)
        self.assertEqual(result.json["counts"]["wow"], 1)
        self.assertEqual(set(self.rows()), {
            (self.first_news, self.first_id, "love"), (self.first_news, self.second_id, "wow"),
            (self.second_news, self.first_id, "sad"),
        })
        self.react("love")
        self.assertIn((self.first_news, self.second_id, "wow"), self.rows())

    def test_guest_sees_counts_but_cannot_react(self):
        self.react("love")
        guest = self.app.test_client()
        html = guest.get(f"/news/{self.first_news}").get_data(as_text=True)
        self.assertIn("Люблю: 1. Войти", html)
        self.assertNotIn("data-reaction-form", html)
        result = self.react(client=guest)
        self.assertEqual(result.status_code, 401)
        parsed = urlsplit(result.json["login_url"])
        self.assertEqual(parsed.path, "/login")
        self.assertEqual(parse_qs(parsed.query)["next"], [f"/news/{self.first_news}#reactions-{self.first_news}"])
        result = self.react(client=guest, json=False)
        self.assertEqual(result.status_code, 303)
        self.assertEqual(urlsplit(result.location).path, "/login")
        self.assertEqual(len(self.rows()), 1)

    def test_pending_rejected_and_missing_news_reject_every_role(self):
        for user_id in (self.first_id, self.second_id, self.admin_id):
            client = self.signed_client(user_id)
            for news_id in (self.pending_news, self.rejected_news, 99999):
                with self.subTest(user=user_id, news=news_id):
                    self.assertEqual(self.react(client=client, news_id=news_id).status_code, 404)
        self.assertEqual(self.rows(), [])
        for path in (f"/news/{self.pending_news}", f"/news/{self.rejected_news}"):
            self.assertNotIn("data-reaction-group", self.client.get(path).get_data(as_text=True))

    def test_missing_csrf_and_get_cannot_change_reactions(self):
        for data in ({"reaction": "fire"}, {"reaction": "fire", "csrf_token": "forged"}):
            result = self.client.post(f"/news/{self.first_news}/reaction", data=data, headers={"Accept": "application/json"})
            self.assertEqual(result.status_code, 400)
            self.assertIsNotNone(result.json)
        self.assertEqual(self.client.get(f"/news/{self.first_news}/reaction").status_code, 405)
        self.assertEqual(self.rows(), [])

    def test_html_fallback_preserves_category_page_and_anchor(self):
        target = f"/?category=science&page=2#reactions-{self.first_news}"
        result = self.react("wow", json=False, next=target)
        self.assertEqual(result.status_code, 303)
        self.assertEqual(result.location, target)
        self.assertEqual(self.rows(), [(self.first_news, self.first_id, "wow")])
        for target in ("https://example.org", "//example.org", "/\\example.org", "https://[bad", "/login"):
            result = self.react("sad", json=False, next=target)
            self.assertEqual(result.location, f"/news/{self.first_news}#reactions-{self.first_news}")

    def test_selection_renders_in_feed_detail_and_my_news(self):
        self.react("fire")
        for path in ("/", "/?category=science", f"/news/{self.first_news}", "/my-news"):
            html = self.client.get(path).get_data(as_text=True)
            self.assertIn('data-reaction="fire" data-label="Огонь" aria-pressed="true"', html)
            self.assertIn('aria-label="Огонь: 1. Убрать реакцию"', html)
            self.assertNotIn(f'id="reactions-{self.pending_news}"', html)
            self.assertNotIn(f'id="reactions-{self.rejected_news}"', html)

    def test_database_enforces_unique_pair_and_allowed_kind(self):
        self.react("like")
        with self.app.app_context():
            for values in (
                {"news_id": self.first_news, "user_id": self.first_id, "kind": "fire"},
                {"news_id": self.second_news, "user_id": self.first_id, "kind": "invalid"},
            ):
                with self.assertRaises(IntegrityError):
                    db.session.execute(db.insert(NewsReaction).values(**values))
                    db.session.commit()
                db.session.rollback()
        self.assertEqual(self.rows(), [(self.first_news, self.first_id, "like")])

    def test_reactions_survive_app_restart_and_remain_removable(self):
        self.react("sad")
        restarted = create_app(self.config)
        self.apps.append(restarted)
        client = self.signed_client(self.first_id, app=restarted)
        html = client.get(f"/news/{self.first_news}").get_data(as_text=True)
        self.assertIn('aria-label="Грустно: 1. Убрать реакцию"', html)
        self.assertIsNone(self.react("sad", client=client).json["selected"])

    def test_database_failure_rolls_back_without_reporting_success(self):
        self.react("like")
        with patch.object(db.session, "commit", side_effect=SQLAlchemyError("test failure")):
            with self.assertLogs(self.app.logger, level="ERROR"):
                result = self.react("fire")
        self.assertEqual(result.status_code, 503)
        self.assertIn("Не удалось сохранить", result.json["message"])
        self.assertEqual(self.rows(), [(self.first_news, self.first_id, "like")])

    def test_feed_loads_counts_in_two_queries_for_whole_page(self):
        self.react()
        statements = []
        with self.app.app_context():
            def collect(connection, cursor, statement, parameters, context, executemany):
                if "news_reactions" in statement.lower():
                    statements.append(statement)
            event.listen(db.engine, "before_cursor_execute", collect)
            try:
                self.assertEqual(self.client.get("/").status_code, 200)
            finally:
                event.remove(db.engine, "before_cursor_execute", collect)
        self.assertEqual(len(statements), 2)
