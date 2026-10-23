"""One model shared by publishing, accounts and moderation."""

from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Index
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="member")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"


class News(db.Model):
    # Retain emil's table and foreign keys so deployed users/news remain valid.
    __tablename__ = "news_items"
    __table_args__ = (
        Index("ix_news_items_feed", "status", "published_at"),
        Index("ix_news_items_author", "author_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    reviewed_at = db.Column(db.DateTime)
    published_at = db.Column(db.DateTime)
    reviewer_note = db.Column(db.Text)
    cover_filename = db.Column(db.String(80))
    cover_data = db.Column(db.LargeBinary)
    event_at = db.Column(db.DateTime)
    location = db.Column(db.String(200))
    registration_url = db.Column(db.String(2048))

    author = db.relationship("User", foreign_keys=[author_id], backref="submitted_items")
    reviewer = db.relationship("User", foreign_keys=[reviewer_id])


NewsItem = News
