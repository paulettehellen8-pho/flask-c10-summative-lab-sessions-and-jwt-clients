"""Productivity API: a small Flask backend where users sign up, log in
and manage their own private notes.

Authentication uses JWT (Flask-JWT-Extended) and passwords are hashed
with Flask-Bcrypt.

Every error is returned as JSON in the same shape: {"errors": ["message"]}
"""
import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, abort, request
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    current_user,
    jwt_required,
)
from flask_migrate import Migrate
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException

from models import db, User, Note

# Load the variables from the .env file (the secret key lives there so it
# never gets pushed to GitHub).
load_dotenv()

# ---------- Limits (kept in one place so they are easy to change) ----------
MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 80       # same as the users.username column
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72        # bcrypt cannot handle passwords longer than this
MAX_TITLE_LENGTH = 150         # same as the notes.title column
MAX_NOTE_CONTENT_LENGTH = 5000
DEFAULT_PER_PAGE = 10
MAX_PER_PAGE = 100
MAX_BODY_BYTES = 1024 * 1024   # reject request bodies over 1 MB
MAX_PAGE = 1_000_000           # stops absurd page numbers from crashing the query
MAX_DB_INTEGER = 2**63 - 1     # the biggest integer SQLite can store

# ---------- App setup ----------
app = Flask(__name__)

secret_key = os.environ.get("JWT_SECRET_KEY")
if not secret_key:
    # Stop straight away with a clear message instead of a confusing
    # error later on when someone tries to log in.
    raise RuntimeError(
        "JWT_SECRET_KEY is not set. Copy .env.example to .env and set it "
        "(see the README)."
    )

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///productivity.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = secret_key
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)

db.init_app(app)
migrate = Migrate(app, db)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

# Allow the React frontend to call this API directly. In development the
# React "proxy" setting already forwards requests to Flask, so this only
# matters if the frontend talks to port 5555 directly.
CORS(app, origins=["http://localhost:4000"])


@app.before_request
def reject_large_requests():
    """Refuse oversized request bodies (413) before any route runs.

    We check the Content-Length header ourselves because Flask's built-in
    MAX_CONTENT_LENGTH setting only kicks in for form data, not JSON.
    """
    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        abort(413)


# ---------- JWT error messages ----------
# By default Flask-JWT-Extended sends its own {"msg": ...} bodies (and a 422
# for bad tokens). These handlers make every auth failure a 401 with our
# standard {"errors": [...]} body.

@jwt.user_lookup_loader
def load_user(jwt_header, jwt_data):
    """Turn the user id stored inside the token into a User object.

    This is what powers `current_user` in the routes below. If it returns
    None (e.g. the account was deleted after the token was issued) the
    user_lookup_error_loader below runs instead.
    """
    return db.session.get(User, int(jwt_data["sub"]))


@jwt.user_lookup_error_loader
def user_not_found(jwt_header, jwt_data):
    return error_response("User no longer exists. Please log in again.", 401)


@jwt.unauthorized_loader
def missing_token(reason):
    return error_response("Authorization token is missing.", 401)


@jwt.invalid_token_loader
def invalid_token(reason):
    return error_response("Authorization token is invalid.", 401)


@jwt.expired_token_loader
def expired_token(jwt_header, jwt_data):
    return error_response("Authorization token has expired. Please log in again.", 401)


# ---------- Helper functions ----------

def error_response(messages, status):
    """Build the standard error body: {"errors": [...]} plus a status code."""
    if isinstance(messages, str):
        messages = [messages]
    return {"errors": messages}, status


def is_text(value):
    """True only if value is a string."""
    return isinstance(value, str)


def get_json_body():
    """Return the request body if it is a JSON object, otherwise None.

    silent=True stops Flask raising its own error on bad JSON, so we can
    send our own message. Valid JSON that is not an object (like a list or
    a number) is rejected too, because the routes below call data.get().
    """
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def find_user_by_username(username):
    """Case-insensitive lookup, so 'Alice' and 'alice' are the same user."""
    return User.query.filter(func.lower(User.username) == username.lower()).first()


def validate_note_field(name, value):
    """Check one note field ("title" or "content").

    Returns (clean_value, error_message). error_message is None when the
    value is fine. Used by both POST and PATCH so the rules stay identical.
    """
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


def get_own_note(note_id):
    """Find a note by id, but only if it belongs to the logged-in user.

    A note owned by someone else gives the same result as a note that does
    not exist (None). That way nobody can find out which note ids exist.
    """
    # An id bigger than SQLite can store would crash the query, and no such
    # note can exist anyway.
    if note_id > MAX_DB_INTEGER:
        return None
    return Note.query.filter_by(id=note_id, user_id=current_user.id).first()


# ---------- Error handlers ----------
# Flask's default error pages are HTML. An API should always answer in JSON.

ERROR_MESSAGES = {
    404: "Resource not found.",
    405: "Method not allowed for this URL.",
    413: "Request body is too large.",
    500: "Something went wrong on the server.",
}


@app.errorhandler(HTTPException)
def handle_http_error(error):
    """Catches 404, 405, 413 and so on, and any unexpected crash (500)."""
    if error.code == 500:
        # A failed database operation leaves the session unusable until it
        # is rolled back.
        db.session.rollback()
    return error_response(ERROR_MESSAGES.get(error.code, error.description), error.code)


# ---------- Routes ----------

@app.route("/")
def home():
    return {"message": "Productivity API is running!"}