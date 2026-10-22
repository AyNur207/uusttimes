"""Validate and re-encode cover images before writing to private app storage."""

from io import BytesIO
from pathlib import Path
from uuid import uuid4

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError


class InvalidCover(ValueError):
    pass


def save_cover(upload):
    limit = 5 * 1024 * 1024
    data = upload.stream.read(limit + 1)
    if len(data) > limit:
        raise InvalidCover("Размер обложки не должен превышать 5 МБ.")
    filename = f"{uuid4().hex}.webp"
    directory = Path(current_app.config["UPLOAD_FOLDER"])
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / filename
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise InvalidCover("Выберите изображение JPG, PNG или WebP.")
            if image.width * image.height > 20_000_000:
                raise InvalidCover("Обложка слишком большая: максимум 20 мегапикселей.")
            image = ImageOps.exif_transpose(image)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA")
            image.thumbnail((1920, 1920))
            image.save(destination, format="WEBP", quality=85)
    except InvalidCover:
        destination.unlink(missing_ok=True)
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        destination.unlink(missing_ok=True)
        raise InvalidCover("Не удалось прочитать изображение. Выберите другой JPG, PNG или WebP.") from error
    return filename
