from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .models import News, NewsReaction, db
from .reaction_types import REACTIONS

reactions_bp = Blueprint("reactions", __name__)


def reaction_context(items):
    ids = [item.id for item in items if item.status == "published"]
    states = {news_id: {"counts": dict.fromkeys(REACTIONS, 0), "selected": None} for news_id in ids}
    if ids:
        rows = db.session.execute(
            db.select(NewsReaction.news_id, NewsReaction.kind, db.func.count())
            .where(NewsReaction.news_id.in_(ids)).group_by(NewsReaction.news_id, NewsReaction.kind)
        )
        for news_id, kind, count in rows:
            if kind in REACTIONS:
                states[news_id]["counts"][kind] = count
        if current_user.is_authenticated:
            for news_id, kind in db.session.execute(
                db.select(NewsReaction.news_id, NewsReaction.kind)
                .where(NewsReaction.news_id.in_(ids), NewsReaction.user_id == current_user.id)
            ):
                states[news_id]["selected"] = kind
    return {"reaction_choices": REACTIONS, "reaction_states": states}


def _return_url(news_id):
    target = request.form.get("next", "")
    try:
        parsed = urlsplit(target)
        if (not parsed.scheme and not parsed.netloc
                and parsed.path in {"/", "/my-news", f"/news/{news_id}"}
                and "\\" not in target and not any(char.isspace() or ord(char) < 32 for char in target)):
            return target
    except ValueError:
        pass
    return url_for("main.news_detail", news_id=news_id) + f"#reactions-{news_id}"


def _failure(message, status, return_url):
    if request.accept_mimetypes.best == "application/json":
        return jsonify(message=message), status
    flash(message, "error")
    return redirect(return_url, code=303)


@reactions_bp.post("/news/<int:news_id>/reaction")
def react(news_id):
    return_url = _return_url(news_id)
    if not current_user.is_authenticated:
        login_url = url_for("auth.login", next=return_url)
        if request.accept_mimetypes.best == "application/json":
            return jsonify(message="Войдите, чтобы оставить реакцию.", login_url=login_url), 401
        flash("Войдите, чтобы оставить реакцию.", "error")
        return redirect(login_url, code=303)
    item = db.session.scalar(db.select(News).where(News.id == news_id, News.status == "published"))
    if item is None:
        if request.accept_mimetypes.best == "application/json":
            return jsonify(message="Опубликованная новость не найдена."), 404
        abort(404)
    kind = request.form.get("reaction")
    if kind not in REACTIONS:
        return _failure("Выберите одну из доступных реакций.", 400, return_url)
    pair = (NewsReaction.news_id == news_id, NewsReaction.user_id == current_user.id)
    selected = db.session.scalar(db.select(NewsReaction.kind).where(*pair))
    try:
        if selected == kind:
            db.session.execute(db.delete(NewsReaction).where(*pair))
        else:
            result = db.session.execute(db.update(NewsReaction).where(*pair).values(kind=kind))
            if result.rowcount == 0:
                try:
                    with db.session.begin_nested():
                        db.session.add(NewsReaction(news_id=news_id, user_id=current_user.id, kind=kind))
                        db.session.flush()
                except IntegrityError:
                    db.session.execute(db.update(NewsReaction).where(*pair).values(kind=kind))
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.error("Не удалось сохранить реакцию в БД.")
        return _failure("Не удалось сохранить реакцию. Попробуйте ещё раз.", 503, return_url)
    if request.accept_mimetypes.best == "application/json":
        state = reaction_context([item])["reaction_states"][news_id]
        return jsonify(news_id=news_id, **state)
    return redirect(return_url, code=303)
