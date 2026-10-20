from flask import current_app
from werkzeug.exceptions import HTTPException

from extensions import db


def error_response(messages, status):
    """The one place that decides what an error looks like: {"errors": [...]}.
    The React client expects a LIST, so a single string is wrapped."""
    if isinstance(messages, str):
        messages = [messages]
    return {"errors": messages}, status


class ApiError(HTTPException):
    """Flask's version of FastAPI's HTTPException. Raise it anywhere:
        raise ApiError("Note not found.", 404)
    It subclasses HTTPException so ONE handler covers our errors and Flask's own
    (404 unknown URL, 405 wrong method)."""

    def __init__(self, messages, code=400):
        super().__init__()
        self.code = code
        self.messages = [messages] if isinstance(messages, str) else messages


def handle_http_error(err):
    # ApiError carries .messages; Flask's built-in errors only have .description.
    messages = getattr(err, "messages", None) or [err.description]
    return error_response(messages, err.code)


def handle_unexpected_error(err):
    # Safety net for bugs we didn't predict.
    db.session.rollback()  # undo any half-finished database work
    # The full traceback goes to the SERVER log only. The user gets a generic
    # message, because error details can leak how the app works.
    current_app.logger.exception("Unhandled error")
    return error_response("Something went wrong on the server.", 500)


def register_error_handlers(app):
    # Flask picks the MOST SPECIFIC handler, so HTTP errors go to the first
    # and everything else falls through to the second.
    app.register_error_handler(HTTPException, handle_http_error)
    app.register_error_handler(Exception, handle_unexpected_error)