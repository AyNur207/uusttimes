"""Application factory for The UUST Times."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import click
from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Войдите, чтобы продолжить."
login_manager.login_message_category = "error"


def create_app(test_config=None):
    root = Path(__file__).resolve().parent.parent

    default_db = f"sqlite:///{root / 'instance' / 'uusttimes.sqlite3'}"
    database_url = os.environ.get("DATABASE_URL") or default_db
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app = Flask(
        __name__,
        static_folder=str(root / "static"),
        template_folder=str(root / "templates"),
        instance_path=str(root / "instance"),
        instance_relative_config=True,
    )
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or "dev-only-insecure-key",
        DONATION_URL=os.environ.get("DONATION_URL", ""),
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from . import models
    from .auth import auth_bp
    from .news import news_bp
    from .routes import main

    app.register_blueprint(main)
    app.register_blueprint(auth_bp)
    app.register_blueprint(news_bp)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(models.User, int(user_id))

    with app.app_context():
        db.create_all()
        admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
        admin_password = os.environ.get("ADMIN_PASSWORD", "")
        if admin_email and admin_password:
            if not models.User.query.filter_by(email=admin_email).first():
                user = models.User(email=admin_email, role="admin")
                user.set_password(admin_password)
                db.session.add(user)
                db.session.commit()

    @app.cli.command("create-admin")
    @click.argument("email")
    def create_admin(email):
        """Создать админа или повысить существующего пользователя."""
        email = email.strip().lower()
        user = models.User.query.filter_by(email=email).first()
        if user:
            user.role = "admin"
            click.echo(f"Пользователь {email} повышен до admin.")
        else:
            password = click.prompt("Пароль", hide_input=True, confirmation_prompt=True)
            user = models.User(email=email, role="admin")
            user.set_password(password)
            db.session.add(user)
            click.echo(f"Создан админ {email}.")
        db.session.commit()

    @app.context_processor
    def publication_context():
        now = datetime.now(timezone(timedelta(hours=5)))
        months = (
            "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря",
        )
        weekdays = (
            "Понедельник", "Вторник", "Среда", "Четверг",
            "Пятница", "Суббота", "Воскресенье",
        )
        donation_url = app.config["DONATION_URL"]
        parsed = urlsplit(donation_url)
        if parsed.scheme != "https" or not parsed.netloc:
            donation_url = ""
        return {
            "publication_date": f"{now.day} {months[now.month - 1]} {now.year}",
            "publication_weekday": weekdays[now.weekday()],
            "publication_iso": now.date().isoformat(),
            "current_year": now.year,
            "donation_url": donation_url,
        }

    return app