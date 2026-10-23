"""Public feed and account-scoped news, with protected unpublished previews."""

from flask import Blueprint, Response, abort, current_app, render_template, send_from_directory
from flask_login import current_user, login_required

from .models import News, db
from .pagination import news_page

main = Blueprint("main", __name__)


@main.get("/")
def index():
    pagination = news_page(
        db.select(News).where(News.status == "published")
        .order_by(News.published_at.desc(), News.id.desc())
    )
    return render_template("index.html", pagination=pagination)


@main.get("/my-news")
@login_required
def my_news():
    pagination = news_page(
        db.select(News).where(News.author_id == current_user.id)
        .order_by(News.created_at.desc(), News.id.desc())
    )
    return render_template("my_news.html", pagination=pagination)


def visible_news(news_id):
    item = db.get_or_404(News, news_id)
    if item.status != "published" and not (
        current_user.is_authenticated and (current_user.is_admin or item.author_id == current_user.id)
    ):
        abort(404)
    return item


@main.get("/news/<int:news_id>")
def news_detail(news_id):
    item = visible_news(news_id)
    response = Response(render_template("news_detail.html", news=item))
    if item.status != "published":
        response.headers["Cache-Control"] = "private, no-store"
    return response


@main.get("/news/<int:news_id>/cover")
def news_cover(news_id):
    item = visible_news(news_id)
    if not item.cover_filename:
        abort(404)
    if item.cover_data:
        response = Response(item.cover_data, mimetype="image/webp")
    else:
        response = send_from_directory(
            current_app.config["UPLOAD_FOLDER"], item.cover_filename, mimetype="image/webp",
        )
    response.headers["Cache-Control"] = "public, max-age=86400" if item.status == "published" else "private, no-store"
    return response


@main.get("/support")
def support():
    return render_template("support.html")
