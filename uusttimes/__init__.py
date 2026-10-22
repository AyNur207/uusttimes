"""Application factory for The UUST Times."""

import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
from flask import Flask
from flask_wtf.csrf import CSRFError, CSRFProtect

from .models import db

csrf = CSRFProtect()


def _local_secret_key(instance_path):
    """Keep anonymous browser sessions valid across local server restarts."""
    key_path = Path(instance_path) / ".secret_key"
    try:
        with key_path.open("x", encoding="utf-8") as file:
            file.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    return key_path.read_text(encoding="utf-8").strip()


def _get_donation_url(value):
    """Accept a public HTTPS link, never embedded credentials or malformed URLs."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or any(char.isspace() or ord(char) < 32 for char in value):
        return ""
    try:
        parsed = urlsplit(value)
        # Accessing port also validates malformed and out-of-range port numbers.
        port = parsed.port
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "\\" in value
            or (port is not None and port != 443)
        ):
            return ""
    except ValueError:
        return ""
    return value


def create_app(test_config=None):
    root = Path(__file__).resolve().parent.parent
    file_config = dotenv_values(root / ".env", encoding="utf-8-sig")
    app = Flask(
        __name__,
        static_folder=str(root / "static"),
        template_folder=str(root / "templates"),
        instance_path=str(root / "instance"),
        instance_relative_config=True,
    )
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", file_config.get("SECRET_KEY")),
        DONATION_URL=os.environ.get("DONATION_URL", file_config.get("DONATION_URL", "")),
        SQLALCHEMY_DATABASE_URI="sqlite:///uusttimes.db",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=str(root / "instance" / "uploads"),
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=90),
    )
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = _local_secret_key(app.instance_path)
    app.config["DONATION_URL"] = _get_donation_url(app.config["DONATION_URL"])
    db.init_app(app)
    csrf.init_app(app)
    with app.app_context():
        db.create_all()

    from .routes import main

    app.register_blueprint(main)

    @app.template_filter("ufa_time")
    def ufa_time(value):
        return value.replace(tzinfo=timezone.utc).astimezone(
            timezone(timedelta(hours=5))
        ).strftime("%d.%m.%Y, %H:%M")

    @app.errorhandler(413)
    def upload_too_large(error):
        from flask import render_template

        return render_template(
            "news_error.html", title="Слишком большой файл",
            message="Выберите обложку до 5 МБ и попробуйте отправить новость ещё раз.",
        ), 413

    @app.errorhandler(CSRFError)
    def csrf_expired(error):
        from flask import render_template

        return render_template(
            "news_error.html", title="Обновите форму",
            message="Не удалось подтвердить отправку. Откройте форму заново и повторите попытку.",
        ), 400

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
        return {
            "publication_date": f"{now.day} {months[now.month - 1]} {now.year}",
            "publication_weekday": weekdays[now.weekday()],
            "publication_iso": now.date().isoformat(),
            "current_year": now.year,
            "donation_url": donation_url,
            "donation_host": urlsplit(donation_url).hostname if donation_url else "",
        }

    return app
