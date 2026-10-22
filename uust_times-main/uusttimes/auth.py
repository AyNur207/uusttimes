"""Registration, login, logout."""

from urllib.parse import urljoin, urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from . import db
from .models import User

auth_bp = Blueprint("auth", __name__)


def _is_safe_next(target):
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and test.netloc == ref.netloc


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    form = {"email": ""}
    if request.method == "POST":
        form["email"] = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""

        errors = []
        if "@" not in form["email"] or "." not in form["email"]:
            errors.append("Введите корректный email.")
        if len(password) < 8:
            errors.append("Пароль должен быть не короче 8 символов.")
        if password != password2:
            errors.append("Пароли не совпадают.")
        if User.query.filter_by(email=form["email"]).first():
            errors.append("Пользователь с таким email уже существует.")

        if errors:
            for e in errors:
                flash(e, "error")
        else:
            user = User(email=form["email"], role="member")
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Аккаунт создан. Добро пожаловать!", "success")
            return redirect(url_for("main.index"))

    return render_template(
        "account.html",
        mode="register",
        title="Регистрация",
        heading="Станьте частью редакции.",
        description="Создайте аккаунт, чтобы предлагать новости.",
        form=form,
    )


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    form = {"email": ""}
    if request.method == "POST":
        form["email"] = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=form["email"]).first()
        if user and user.check_password(password):
            login_user(user)
            flash("Вы вошли.", "success")
            next_url = request.args.get("next")
            return redirect(next_url if _is_safe_next(next_url) else url_for("main.index"))
        flash("Неверный email или пароль.", "error")

    return render_template(
        "account.html",
        mode="login",
        title="Вход",
        heading="С возвращением в Times.",
        description="Войдите, чтобы предлагать новости.",
        form=form,
    )


@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("Вы вышли.", "success")
    return redirect(url_for("main.index"))