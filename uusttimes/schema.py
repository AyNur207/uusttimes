from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateColumn

from .models import News, db


def upgrade_schema():
    inspector = inspect(db.engine)
    if not inspector.has_table("news_items"):
        db.metadata.create_all(db.engine)
        return
    existing = {column["name"] for column in inspector.get_columns("news_items")}
    with db.engine.begin() as connection:
        for column in News.__table__.columns:
            if column.name not in existing:
                definition = str(CreateColumn(column).compile(dialect=db.engine.dialect))
                connection.execute(text(f'ALTER TABLE news_items ADD COLUMN {definition}'))
        connection.execute(text("UPDATE news_items SET status = 'published' WHERE status = 'approved'"))
        connection.execute(text(
            "UPDATE news_items SET published_at = COALESCE(reviewed_at, created_at) "
            "WHERE status = 'published' AND published_at IS NULL"
        ))
    for index in News.__table__.indexes:
        index.create(db.engine, checkfirst=True)


def initialize_database():
    if inspect(db.engine).has_table("news_items"):
        upgrade_schema()
    db.create_all()
