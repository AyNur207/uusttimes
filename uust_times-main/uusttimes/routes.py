"""Public pages: home feed and support."""

from flask import Blueprint, render_template

from .models import NewsItem

main = Blueprint("main", __name__)


@main.get("/")
def index():
    news = (
        NewsItem.query.filter_by(status="approved")
        .order_by(NewsItem.reviewed_at.desc())
        .all()
    )
    return render_template("index.html", news=news)


@main.get("/support")
def support():
    return render_template("support.html")