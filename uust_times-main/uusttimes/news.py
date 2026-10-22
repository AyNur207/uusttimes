"""Members propose news, admins moderate."""

from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import db
from .models import NewsItem

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
@login_required
def submit():
    form = {"title": "", "body": ""}
    if request.method == "POST":
        form["title"] = (request.form.get("title") or "").strip()
        form["body"] = (request.form.get("body") or "").strip()

        errors = []
        if len(form["title"]) < 5:
            errors.append("Заголовок должен быть не короче 5 символов.")
        if len(form["body"]) < 20:
            errors.append("Текст должен быть не короче 20 символов.")

        if errors:
            for e in errors:
                flash(e, "error")
        else:
            item = NewsItem(
                title=form["title"],
                body=form["body"],
                author_id=current_user.id,
                status="pending",
            )
            db.session.add(item)
            db.session.commit()
            flash("Новость отправлена на модерацию.", "success")
            return redirect(url_for("main.index"))

    return render_template("submit.html", title="Предложить новость", form=form)


@news_bp.get("/moderation")
@admin_required
def moderation():
    pending = (
        NewsItem.query.filter_by(status="pending")
        .order_by(NewsItem.created_at.asc())
        .all()
    )
    return render_template("moderation.html", title="Модерация", items=pending)


@news_bp.post("/moderation/<int:item_id>/approve")
@admin_required
def approve(item_id):
    item = db.session.get(NewsItem, item_id)
    if item is None:
        abort(404)
    if item.status != "pending":
        flash("Эта новость уже обработана.", "error")
        return redirect(url_for("news.moderation"))
    item.status = "approved"
    item.reviewer_id = current_user.id
    item.reviewed_at = datetime.now(timezone.utc)
    db.session.commit()
    flash("Новость опубликована.", "success")
    return redirect(url_for("news.moderation"))


@news_bp.post("/moderation/<int:item_id>/reject")
@admin_required
def reject(item_id):
    item = db.session.get(NewsItem, item_id)
    if item is None:
        abort(404)
    if item.status != "pending":
        flash("Эта новость уже обработана.", "error")
        return redirect(url_for("news.moderation"))
    item.status = "rejected"
    item.reviewer_id = current_user.id
    item.reviewed_at = datetime.now(timezone.utc)
    db.session.commit()
    flash("Новость отклонена.", "success")
    return redirect(url_for("news.moderation"))