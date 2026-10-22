"""News submission validation, independent of authentication."""

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from urllib.parse import urlsplit
from wtforms import DateTimeLocalField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, URL, ValidationError


def strip_text(value):
    return value.strip() if isinstance(value, str) else value


class NewsForm(FlaskForm):
    title = StringField(
        "Заголовок",
        filters=[strip_text],
        validators=[
            DataRequired(message="Укажите заголовок."),
            Length(min=3, max=160, message="Заголовок должен содержать от 3 до 160 символов."),
        ],
        render_kw={"maxlength": 160, "placeholder": "Что происходит в университете?"},
    )
    body = TextAreaField(
        "Текст новости",
        filters=[strip_text],
        validators=[
            DataRequired(message="Напишите текст новости."),
            Length(min=10, max=20000, message="Текст должен содержать от 10 до 20 000 символов."),
        ],
        render_kw={"rows": 10, "maxlength": 20000, "placeholder": "Расскажите о событии: что, где и когда будет происходить."},
    )
    cover = FileField(
        "Обложка",
        validators=[FileAllowed(["jpg", "jpeg", "png", "webp"], "Выберите JPG, PNG или WebP.")],
        render_kw={"accept": ".jpg,.jpeg,.png,.webp"},
    )
    event_at = DateTimeLocalField(
        "Дата и время события",
        format="%Y-%m-%dT%H:%M",
        validators=[Optional()],
    )
    location = StringField(
        "Место проведения",
        filters=[strip_text],
        validators=[Optional(), Length(max=200, message="Укажите место не длиннее 200 символов.")],
        render_kw={"maxlength": 200, "placeholder": "Например, корпус 1, аудитория 205"},
    )
    registration_url = StringField(
        "Ссылка на регистрацию",
        filters=[strip_text],
        validators=[
            Optional(),
            Length(max=2048, message="Ссылка слишком длинная."),
            URL(require_tld=True, message="Укажите полную ссылку, начинающуюся с http:// или https://."),
        ],
        render_kw={"maxlength": 2048, "placeholder": "https://…"},
    )
    submit = SubmitField("Опубликовать новость")

    def validate_registration_url(self, field):
        if not field.data:
            return
        try:
            parsed = urlsplit(field.data)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or "\\" in field.data
                or any(char.isspace() or ord(char) < 32 for char in field.data)
            ):
                raise ValueError
            _ = parsed.port
        except ValueError as error:
            raise ValidationError("Укажите корректную ссылку http:// или https:// без логина и пароля.") from error

    def validate_event_at(self, field):
        if field.data and not 1900 <= field.data.year <= 2100:
            raise ValidationError("Укажите год события от 1900 до 2100.")
