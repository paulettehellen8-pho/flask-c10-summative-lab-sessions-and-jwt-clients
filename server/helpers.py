"""Shared validation and response helpers for the API."""
from sqlalchemy import func

from models import Note, User

MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 80
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72  # bcrypt's input limit
MAX_TITLE_LENGTH = 150
MAX_NOTE_CONTENT_LENGTH = 5000
DEFAULT_PER_PAGE = 10
MAX_PER_PAGE = 100
MAX_BODY_BYTES = 1024 * 1024
MAX_PAGE = 1_000_000
MAX_DB_INTEGER = 2**63 - 1


def error_response(messages, status):
    """Return errors in the API's standard JSON shape."""
    if isinstance(messages, str):
        messages = [messages]
    return {"errors": messages}, status


def is_text(value):
    return isinstance(value, str)


def get_json_body(request):
    """Accept only a JSON object, not arrays, strings, or malformed JSON."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def find_user_by_username(username):
    """Use a case-insensitive username lookup."""
    return User.query.filter(func.lower(User.username) == username.lower()).first()


def validate_note_field(name, value):
    """Return (clean_value, error_message) for a note field."""
    max_lengths = {"title": MAX_TITLE_LENGTH, "content": MAX_NOTE_CONTENT_LENGTH}
    label = name.capitalize()
    if not is_text(value):
        return None, f"{label} must be text."
    value = value.strip()
    if not value:
        return None, f"{label} cannot be empty."
    if len(value) > max_lengths[name]:
        return None, f"{label} must be {max_lengths[name]} characters or fewer."
    return value, None


def get_own_note(note_id, user):
    """Do not reveal whether another user's note exists."""
    if note_id > MAX_DB_INTEGER:
        return None
    return Note.query.filter_by(id=note_id, user_id=user.id).first()
