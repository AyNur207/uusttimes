"""Registration and signed login sessions with validated CSRF forms."""

from urllib.parse import urljoin, urlparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from .forms import LoginForm, RegisterForm
from .models import User, db

auth_bp = Blueprint("auth", __name__)


def _is_safe_next(target):
    if not target or "\\" in target or any(ord(char) < 32 for char in target):
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and test.netloc == ref.netloc


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = RegisterForm()
    if form.validate_on_submit():
        user = User(email=form.email.data, role="member")
        user.set_password(form.password.data)
        try:
            db.session.add(user)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            form.email.errors.append("Пользователь с таким email уже существует.")
        else:
            login_user(user)
            session.permanent = True
            flash("Аккаунт создан. Добро пожаловать!", "success")
            return redirect(url_for("main.my_news"), code=303)
    return render_template(
        "account.html", mode="register", title="Регистрация", form=form,
        heading="Станьте частью редакции.", description="Создайте аккаунт, чтобы предлагать новости.",
    ), (400 if request.method == "POST" else 200)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(db.select(User).where(User.email == form.email.data))
        if user and user.check_password(form.password.data):
            login_user(user)
            session.permanent = True
            flash("Вы вошли.", "success")
            next_url = request.args.get("next")
            return redirect(next_url if _is_safe_next(next_url) else url_for("main.my_news"), code=303)
        form.password.errors.append("Неверный email или пароль.")
    return render_template(
        "account.html", mode="login", title="Вход", form=form,
        heading="С возвращением в Times.", description="Войдите, чтобы предлагать новости.",
    ), (400 if request.method == "POST" else 200)


@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("Вы вышли.", "success")
    return redirect(url_for("main.index"), code=303)
