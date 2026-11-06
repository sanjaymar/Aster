import re

CITATION = re.compile(r"\[\[([SCV]):([^\]\s]+)\]\]")


class Problem(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def plain(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def required(session, model, key):
    row = session.get(model, key)
    if row is None:
        raise Problem("记录不存在", 404)
    return row
