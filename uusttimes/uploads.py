from io import BytesIO
from pathlib import Path
from uuid import uuid4

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError


class InvalidCover(ValueError):
    pass


def encode_cover(data):
    if len(data) > 5 * 1024 * 1024:
        raise InvalidCover("Размер обложки не должен превышать 5 МБ.")
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
            output = BytesIO()
            image.save(output, format="WEBP", quality=85)
            return output.getvalue()
    except InvalidCover:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise InvalidCover("Не удалось прочитать изображение. Выберите другой JPG, PNG или WebP.") from error


def save_cover(upload):
    data = encode_cover(upload.stream.read(5 * 1024 * 1024 + 1))
    filename = f"{uuid4().hex}.webp"
    directory = Path(current_app.config["UPLOAD_FOLDER"])
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / filename
    try:
        destination.write_bytes(data)
    except OSError:
        destination.unlink(missing_ok=True)
        raise
    return filename
