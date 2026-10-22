"""Persistent news records; timestamps are stored as naive UTC values."""

from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, Index

db = SQLAlchemy()


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class News(db.Model):
    __tablename__ = "news"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'published', 'rejected')"),
        Index("ix_news_feed", "status", "published_at"),
        Index("ix_news_author", "author_token", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    author_token = db.Column(db.String(64), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    body = db.Column(db.Text, nullable=False)
    cover_filename = db.Column(db.String(80))
    event_at = db.Column(db.DateTime)
    location = db.Column(db.String(200))
    registration_url = db.Column(db.String(2048))
    status = db.Column(db.String(20), nullable=False, default="published")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    published_at = db.Column(db.DateTime, nullable=False, default=utc_now)
