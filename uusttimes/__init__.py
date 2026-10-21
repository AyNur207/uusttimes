"""Application factory for The UUST Times."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask


def create_app(test_config=None):
    root = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        static_folder=str(root / "static"),
        template_folder=str(root / "templates"),
        instance_path=str(root / "instance"),
        instance_relative_config=True,
    )
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        DONATION_URL=os.environ.get("DONATION_URL", ""),
    )
    if test_config:
        app.config.update(test_config)

    from .routes import main

    app.register_blueprint(main)

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
