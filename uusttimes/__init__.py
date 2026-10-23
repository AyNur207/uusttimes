import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import click
from dotenv import dotenv_values
from flask import Flask, jsonify, request, url_for
from flask_login import LoginManager
from flask_wtf.csrf import CSRFError, CSRFProtect
from email_validator import EmailNotValidError, validate_email
from sqlalchemy.exc import IntegrityError

from .models import User, db
from .schema import initialize_database

csrf = CSRFProtect()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Войдите, чтобы продолжить."
login_manager.login_message_category = "error"


def _database_uri(value):
    if not value:
        return "sqlite:///uusttimes.sqlite3"
    for prefix in ("postgres://", "postgresql://"):
        if value.startswith(prefix):
            return "postgresql+psycopg://" + value[len(prefix):]
    return value


def _local_secret_key(instance_path):
    key_path = Path(instance_path) / ".secret_key"
    try:
        with key_path.open("x", encoding="utf-8") as file:
            file.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    return key_path.read_text(encoding="utf-8").strip()


def _get_donation_url(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or any(char.isspace() or ord(char) < 32 for char in value):
        return ""
    try:
        parsed = urlsplit(value)
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
    def setting(name, default=None):
        return os.environ.get(name, file_config.get(name, default))
    app = Flask(
        __name__,
        static_folder=str(root / "static"),
        template_folder=str(root / "templates"),
        instance_path=str(root / "instance"),
        instance_relative_config=True,
    )
    app.config.from_mapping(
        SECRET_KEY=setting("SECRET_KEY"),
        DONATION_URL=setting("DONATION_URL", ""),
        SQLALCHEMY_DATABASE_URI=_database_uri(setting("DATABASE_URL")),
        ADMIN_EMAIL=setting("ADMIN_EMAIL", ""),
        ADMIN_PASSWORD=setting("ADMIN_PASSWORD", ""),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=setting("UPLOAD_FOLDER") or str(root / "instance" / "uploads"),
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=90),
        SEED_NEWS=None,
        NEWS_CONTENT_FILE=str(root / "permanent.md"),
    )
    if test_config:
        app.config.update(test_config)
    if app.config["SEED_NEWS"] is None:
        app.config["SEED_NEWS"] = not app.testing
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = _local_secret_key(app.instance_path)
    app.config["DONATION_URL"] = _get_donation_url(app.config["DONATION_URL"])
    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    with app.app_context():
        initialize_database()
        admin_email = (app.config["ADMIN_EMAIL"] or "").strip().lower()
        admin_password = app.config["ADMIN_PASSWORD"] or ""
        if admin_email and admin_password:
            try:
                validate_email(admin_email, check_deliverability=False)
            except EmailNotValidError as error:
                raise ValueError("ADMIN_EMAIL должен содержать корректный email.") from None
            if not 8 <= len(admin_password) <= 256:
                raise ValueError("ADMIN_PASSWORD должен содержать от 8 до 256 символов.")
            if not db.session.scalar(db.select(User).where(User.email == admin_email)):
                user = User(email=admin_email, role="admin")
                user.set_password(admin_password)
                db.session.add(user)
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    if not db.session.scalar(db.select(User).where(User.email == admin_email)):
                        raise
        if app.config["SEED_NEWS"]:
            from .content import import_news

            import_news(app.config["NEWS_CONTENT_FILE"], app.static_folder)

    @app.cli.command("import-news")
    @click.option("--update", is_flag=True, help="Обновить тексты и обложки существующих ID из Markdown.")
    def import_bundled_news(update):
        from .content import import_news

        try:
            created, updated = import_news(app.config["NEWS_CONTENT_FILE"], app.static_folder, update=update)
        except (OSError, ValueError) as error:
            raise click.ClickException(str(error)) from None
        click.echo(f"Добавлено: {created}. Обновлено: {updated}.")

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (ValueError, TypeError):
            return None

    @app.cli.command("create-admin")
    @click.argument("email")
    def create_admin(email):
        email = email.strip().lower()
        try:
            validate_email(email, check_deliverability=False)
        except EmailNotValidError:
            raise click.ClickException("Введите корректный email.") from None
        user = db.session.scalar(db.select(User).where(User.email == email))
        if user is None:
            password = click.prompt("Пароль", hide_input=True, confirmation_prompt=True)
            if not 8 <= len(password) <= 256:
                raise click.ClickException("Пароль должен содержать от 8 до 256 символов.")
            user = User(email=email, role="admin")
            user.set_password(password)
            db.session.add(user)
        else:
            user.role = "admin"
        db.session.commit()
        click.echo(f"Права администратора назначены: {email}")

    from .routes import main
    from .auth import auth_bp
    from .news import news_bp
    from .reactions import reactions_bp

    app.register_blueprint(main)
    app.register_blueprint(auth_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(reactions_bp)

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

        if request.endpoint == "reactions.react" and request.accept_mimetypes.best == "application/json":
            return jsonify(message="Обновите страницу и попробуйте оставить реакцию ещё раз."), 400
        return render_template(
            "news_error.html", title="Обновите форму",
            message="Не удалось подтвердить отправку. Откройте форму заново и повторите попытку.",
            return_url=(url_for("main.news_detail", news_id=request.view_args["news_id"])
                        if request.endpoint == "reactions.react" else
                        url_for("auth.login" if request.endpoint and request.endpoint.startswith("auth.") else "news.submit")),
        ), 400

    @app.errorhandler(403)
    @app.errorhandler(404)
    def unavailable_page(error):
        from flask import render_template

        return render_template("error.html", code=error.code), error.code

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
