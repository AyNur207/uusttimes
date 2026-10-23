

import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError

from .categories import CATEGORIES
from .models import News, User, db, utc_now
from .uploads import encode_cover

EDITOR_EMAIL = "edition@uusttimes.invalid"


def read_news(path, static_root):
    """Each ## news-NNN block contains key: value metadata, ---, then plain text."""
    text = Path(path).read_text(encoding="utf-8-sig")
    blocks = re.split(r"^## (news-\d{3,})\s*$", text, flags=re.MULTILINE)
    if len(blocks) == 1:
        raise ValueError("Не найдены новости с заголовками ## news-001.")
    records = []
    seen = set()
    static_root = Path(static_root).resolve()
    for key, block in zip(blocks[1::2], blocks[2::2]):
        if key in seen:
            raise ValueError(f"Повторяется ID: {key}.")
        seen.add(key)
        parts = re.split(r"^---\s*$", block, maxsplit=1, flags=re.MULTILINE)
        if len(parts) != 2:
            raise ValueError(f"{key}: отделите поля от текста строкой ---.")
        fields = {}
        for line in parts[0].strip().splitlines():
            name, separator, value = line.partition(":")
            if not separator or name not in {"title", "category", "image", "link", "location"} or name in fields:
                raise ValueError(f"{key}: неизвестное или повторяющееся поле {name}.")
            fields[name] = value.strip()
        body = parts[1].strip()
        title = fields.get("title", "")
        category = fields.get("category", "")
        if not 3 <= len(title) <= 160 or not 10 <= len(body) <= 20000:
            raise ValueError(f"{key}: проверьте длину заголовка и текста.")
        if category not in CATEGORIES:
            raise ValueError(f"{key}: неизвестная категория {category}.")
        link = fields.get("link") or None
        if link:
            try:
                url = urlsplit(link)
                if (len(link) > 2048 or url.scheme not in {"http", "https"} or not url.hostname
                        or url.username is not None or url.password is not None or "\\" in link
                        or any(char.isspace() or ord(char) < 32 for char in link)):
                    raise ValueError
                _ = url.port
            except ValueError:
                raise ValueError(f"{key}: некорректная ссылка http:// или https://.") from None
        location = fields.get("location") or None
        if location and len(location) > 200:
            raise ValueError(f"{key}: место проведения длиннее 200 символов.")
        image = None
        if fields.get("image"):
            image = (static_root / fields["image"]).resolve()
            if not image.is_relative_to(static_root) or not image.is_file():
                raise ValueError(f"{key}: изображение должно существовать внутри static.")
        records.append(dict(seed_key=key, title=title, body=body, category=category,
                            external_url=link, location=location, image=image))
    return records


def import_news(path, static_root, update=False, _retry=True):
    """Startup inserts missing IDs only; explicit --update refreshes their content."""
    records = read_news(path, static_root)
    created = updated = 0
    try:
        existing = {item.seed_key: item for item in db.session.scalars(
            db.select(News).where(News.seed_key.in_([row["seed_key"] for row in records]))
        )}
        missing = any(row["seed_key"] not in existing for row in records)
        author = None
        if missing:
            author = db.session.scalar(db.select(User).where(User.email == EDITOR_EMAIL))
            if author is None:
                author = User(email=EDITOR_EMAIL, role="member")
                # Reserved, non-routable address and an unknown random password.
                author.set_password(secrets.token_urlsafe(48))
                db.session.add(author)
                db.session.flush()
        now = utc_now()
        for record in records:
            values = dict(record)
            image = values.pop("image")
            item = existing.get(values["seed_key"])
            if item is not None and not update:
                continue
            cover = encode_cover(image.read_bytes()) if image else None
            values.update(cover_data=cover, cover_filename=f"{values['seed_key']}.webp" if cover else None)
            if item is None:
                item = News(author_id=author.id, status="published", created_at=now, published_at=now, **values)
                db.session.add(item)
                created += 1
            else:
                for name, value in values.items():
                    setattr(item, name, value)
                # Keep the original date, author and any later moderation decision.
                updated += 1
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if _retry:
            return import_news(path, static_root, update=update, _retry=False)
        raise
    except Exception:
        db.session.rollback()
        raise
    return created, updated
