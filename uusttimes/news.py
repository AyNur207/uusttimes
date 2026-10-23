from datetime import timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from .forms import NewsForm, RejectForm
from .models import News, NewsReaction, db, utc_now
from .pagination import news_page
from .uploads import InvalidCover, save_cover

news_bp = Blueprint("news", __name__)


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapper


@news_bp.route("/submit", methods=["GET", "POST"])
@news_bp.route("/news/new", methods=["GET", "POST"])
@login_required
def submit():
    form = NewsForm()
    form.submit.label.text = "Опубликовать новость" if current_user.is_admin else "Отправить на проверку"
    if form.validate_on_submit():
        cover_filename = None
        cover_data = None
        if form.cover.data:
            try:
                cover_filename = save_cover(form.cover.data)
                cover_data = (Path(current_app.config["UPLOAD_FOLDER"]) / cover_filename).read_bytes()
            except InvalidCover as error:
                form.cover.errors.append(str(error))
                return render_template("new_news.html", form=form), 400
        event_at = form.event_at.data
        if event_at:
            event_at = event_at.replace(tzinfo=timezone(timedelta(hours=5))).astimezone(timezone.utc).replace(tzinfo=None)
        now = utc_now()
        publish_now = current_user.is_admin
        item = News(
            author_id=current_user.id, title=form.title.data, body=form.body.data,
            category=form.category.data,
            cover_filename=cover_filename, cover_data=cover_data, event_at=event_at,
            location=form.location.data or None, registration_url=form.registration_url.data or None,
            status="published" if publish_now else "pending", created_at=now,
            published_at=now if publish_now else None,
            reviewed_at=now if publish_now else None,
            reviewer_id=current_user.id if publish_now else None,
        )
        try:
            db.session.add(item)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            if cover_filename:
                (Path(current_app.config["UPLOAD_FOLDER"]) / cover_filename).unlink(missing_ok=True)
            current_app.logger.error("Не удалось сохранить новость в БД.")
            form.form_errors.append("Не удалось сохранить новость. Попробуйте ещё раз.")
            return render_template("new_news.html", form=form), 500
        flash(
            "Новость опубликована и появилась в общей ленте." if publish_now
            else "Новость отправлена на проверку. Статус доступен в «Моих новостях».", "success",
        )
        return redirect(url_for("main.index" if publish_now else "main.my_news"), code=303)
    return render_template("new_news.html", form=form), (400 if request.method == "POST" else 200)


@news_bp.get("/moderation")
@admin_required
def moderation():
    pagination = news_page(
        db.select(News).where(News.status == "pending").order_by(News.created_at.asc(), News.id.asc())
    )
    return render_template("moderation.html", pagination=pagination)


def moderation_redirect():
    return redirect(url_for("news.moderation", page=max(1, request.args.get("page", 1, type=int))), code=303)


@news_bp.post("/moderation/<int:item_id>/approve")
@admin_required
def approve(item_id):
    item = db.get_or_404(News, item_id)
    if item.status != "pending":
        flash("Эта новость уже обработана.", "error")
        return moderation_redirect()
    item.status = "published"
    item.reviewer_id = current_user.id
    item.reviewed_at = item.published_at = utc_now()
    item.reviewer_note = None
    db.session.commit()
    flash("Новость опубликована.", "success")
    return moderation_redirect()


@news_bp.post("/moderation/<int:item_id>/reject")
@admin_required
def reject(item_id):
    item = db.get_or_404(News, item_id)
    if item.status != "pending":
        flash("Эта новость уже обработана.", "error")
        return moderation_redirect()
    form = RejectForm()
    if not form.validate_on_submit():
        for error in form.reason.errors:
            flash(error, "error")
        return moderation_redirect()
    item.status = "rejected"
    item.reviewer_id = current_user.id
    item.reviewed_at = utc_now()
    item.reviewer_note = form.reason.data
    item.published_at = None
    db.session.commit()
    flash("Новость отклонена. Причина доступна автору.", "success")
    return moderation_redirect()


@news_bp.post("/news/<int:news_id>/delete")
@admin_required
def delete_news(news_id):
    item = db.session.scalar(
        db.select(News).where(News.id == news_id, News.status == "published").with_for_update()
    )
    if item is None:
        abort(404)
    if request.form.get("confirm") != "yes":
        flash("Подтвердите удаление новости.", "error")
        return redirect(url_for("main.news_detail", news_id=news_id), code=303)
    cover_filename = item.cover_filename
    try:
        db.session.execute(db.delete(NewsReaction).where(NewsReaction.news_id == news_id))
        item.status = "deleted"
        item.title = ""
        item.body = ""
        item.cover_data = None
        item.cover_filename = None
        item.external_url = None
        item.registration_url = None
        item.event_at = None
        item.location = None
        item.reviewer_note = None
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.error("Не удалось удалить новость из БД.")
        flash("Не удалось удалить новость. Попробуйте ещё раз.", "error")
        return redirect(url_for("main.news_detail", news_id=news_id), code=303)
    if cover_filename:
        directory = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
        cover_path = (directory / cover_filename).resolve()
        shared = db.session.scalar(db.select(News.id).where(News.cover_filename == cover_filename).limit(1))
        if cover_path.parent == directory and not shared:
            try:
                cover_path.unlink(missing_ok=True)
            except OSError:
                current_app.logger.warning("Не удалось очистить локальный кеш обложки удалённой новости.")
    flash("Новость удалена.", "success")
    return redirect(url_for("main.index"), code=303)
