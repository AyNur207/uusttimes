from flask import request

from .models import db


def news_page(statement):
    page = max(1, request.args.get("page", 1, type=int))
    result = db.paginate(statement, page=page, per_page=10, error_out=False)
    if page > max(1, result.pages):
        result = db.paginate(statement, page=max(1, result.pages), per_page=10, error_out=False)
    return result
