"""Public news publishing without registration or moderation for the prototype."""

import secrets
from datetime import timedelta, timezone
from pathlib import Path

from flask import (
    Blueprint, current_app, flash, redirect, render_template, request,
    send_from_directory, session, url_for,
)
from sqlalchemy.exc import SQLAlchemyError

from .forms import NewsForm
from .models import News, db, utc_now
from .uploads import InvalidCover, save_cover

main = Blueprint("main", __name__)


def anonymous_author():
    if "author_token" not in session:
        session["author_token"] = secrets.token_urlsafe(32)
    session.permanent = True
    return session["author_token"]


def news_page(statement):
    page = max(1, request.args.get("page", 1, type=int))
    return db.paginate(statement, page=page, per_page=10, error_out=False)


@main.get("/")
def index():
    pagination = news_page(
        db.select(News).where(News.status == "published")
        .order_by(News.published_at.desc(), News.id.desc())
    )
    return render_template("index.html", pagination=pagination)


@main.get("/my-news")
def my_news():
    pagination = news_page(
        db.select(News).where(News.author_token == anonymous_author())
        .order_by(News.created_at.desc(), News.id.desc())
    )
    return render_template("my_news.html", pagination=pagination)


@main.route("/news/new", methods=["GET", "POST"])
def new_news():
    author_token = anonymous_author()
    form = NewsForm()
    if form.validate_on_submit():
        cover_filename = None
        if form.cover.data:
            try:
                cover_filename = save_cover(form.cover.data)
            except InvalidCover as error:
                form.cover.errors.append(str(error))
                return render_template("new_news.html", form=form), 400
        event_at = form.event_at.data
        if event_at:
            event_at = event_at.replace(
                tzinfo=timezone(timedelta(hours=5))
            ).astimezone(timezone.utc).replace(tzinfo=None)
        now = utc_now()
        news = News(
            author_token=author_token, title=form.title.data, body=form.body.data,
            cover_filename=cover_filename, event_at=event_at,
            location=form.location.data or None,
            registration_url=form.registration_url.data or None,
            status="published", created_at=now, published_at=now,
        )
        try:
            db.session.add(news)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            if cover_filename:
                (Path(current_app.config["UPLOAD_FOLDER"]) / cover_filename).unlink(missing_ok=True)
            current_app.logger.exception("Failed to save submitted news")
            form.form_errors.append("Не удалось сохранить новость. Попробуйте ещё раз.")
            return render_template("new_news.html", form=form), 500
        flash("Новость опубликована и появилась в общей ленте.", "success")
        return redirect(url_for("main.index"), code=303)
    return render_template("new_news.html", form=form), (400 if request.method == "POST" else 200)


@main.get("/news/<int:news_id>")
def news_detail(news_id):
    news = db.first_or_404(db.select(News).where(News.id == news_id, News.status == "published"))
    return render_template("news_detail.html", news=news)


@main.get("/news/<int:news_id>/cover")
def news_cover(news_id):
    news = db.first_or_404(db.select(News).where(News.id == news_id, News.status == "published"))
    if not news.cover_filename:
        from flask import abort

        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"], news.cover_filename,
        mimetype="image/webp", max_age=86400,
    )


@main.get("/login")
def login():
    return render_template(
        "account.html", mode="login", title="Вход",
        heading="С возвращением в Times.",
        description="Вход в личный кабинет скоро появится. А пока читайте ленту — она открыта для всех.",
    )


@main.get("/register")
def register():
    return render_template(
        "account.html", mode="register", title="Регистрация",
        heading="Станьте частью редакции.",
        description="Регистрация скоро откроется. Вы сможете предлагать новости и рассказывать о жизни университета.",
    )


@main.get("/support")
def support():
    return render_template("support.html")
