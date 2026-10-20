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


@app.route("/signup", methods=["POST"])
def signup():
    data = get_json_body()
    if data is None:
        return error_response("Request body must be a JSON object.", 400)

    username = data.get("username", "")
    password = data.get("password", "")
    password_confirmation = data.get("password_confirmation", "")

    # Numbers, lists, null etc. would crash the string checks below
    if not (is_text(username) and is_text(password) and is_text(password_confirmation)):
        return error_response(
            "Username, password and password_confirmation must be text.", 400
        )

    # Spaces around a username are almost always a typo. (Passwords are NOT
    # stripped, spaces can be a real part of a password.)
    username = username.strip()

    # Collect every problem so the user can fix them all in one go
    errors = []

    if not username:
        errors.append("Username is required.")
    elif not MIN_USERNAME_LENGTH <= len(username) <= MAX_USERNAME_LENGTH:
        errors.append(
            f"Username must be {MIN_USERNAME_LENGTH}-{MAX_USERNAME_LENGTH} characters."
        )

    if not password.strip():
        errors.append("Password is required.")
    elif len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    elif len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        # Counted in bytes because bcrypt works on bytes (emoji and accented
        # letters take more than one byte each)
        errors.append(f"Password must be at most {MAX_PASSWORD_BYTES} bytes long.")

    if not password_confirmation:
        errors.append("Password confirmation is required.")
    elif password != password_confirmation:
        errors.append("Passwords do not match.")

    if errors:
        return error_response(errors, 400)

    if find_user_by_username(username):
        return error_response("Username already exists.", 409)

    # Hash the password before saving it. The real password is never stored.
    password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
    new_user = User(username=username, password_hash=password_hash)

    try:
        db.session.add(new_user)
        db.session.commit()
    except IntegrityError:
        # Two people signed up with the same name at the same moment, so
        # the database's unique rule caught it after our check above.
        db.session.rollback()
        return error_response("Username already exists.", 409)

    # The token stores the user's id (as a string, JWT requires that)
    token = create_access_token(identity=str(new_user.id))

    return {"token": token, "user": new_user.to_dict()}, 201


@app.route("/login", methods=["POST"])
def login():
    data = get_json_body()
    if data is None:
        return error_response("Request body must be a JSON object.", 400)

    username = data.get("username", "")
    password = data.get("password", "")

    if not (is_text(username) and is_text(password)):
        return error_response("Username and password must be text.", 400)

    username = username.strip()

    if not username or not password:
        return error_response("Username and password are required.", 400)

    user = find_user_by_username(username)

    # Same message for "no such user" and "wrong password", so an attacker
    # cannot use the login form to find out which usernames exist.
    if user is None or not bcrypt.check_password_hash(user.password_hash, password):
        return error_response("Invalid username or password.", 401)

    token = create_access_token(identity=str(user.id))

    return {"token": token, "user": user.to_dict()}, 200


@app.route("/me", methods=["GET"])
@jwt_required()
def me():
    """The frontend calls this on page load to check if the token is still valid."""
    return current_user.to_dict(), 200


@app.route("/notes", methods=["POST"])
@jwt_required()
def create_note():
    data = get_json_body()
    if data is None:
        return error_response("Request body must be a JSON object.", 400)

    errors = []
    clean = {}

    for field in ("title", "content"):
        if field not in data:
            errors.append(f"{field.capitalize()} is required.")
            continue
        value, error = validate_note_field(field, data[field])
        if error:
            errors.append(error)
        else:
            clean[field] = value

    if errors:
        return error_response(errors, 400)

    # The owner always comes from the token, never from the request body.
    # That means a user cannot create a note for somebody else.
    new_note = Note(
        title=clean["title"],
        content=clean["content"],
        user_id=current_user.id,
    )
    db.session.add(new_note)
    db.session.commit()

    return new_note.to_dict(), 201


@app.route("/notes", methods=["GET"])
@jwt_required()
def get_notes():
    # Query strings are always text, so convert them to numbers ourselves
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", DEFAULT_PER_PAGE))
    except ValueError:
        return error_response("page and per_page must be whole numbers.", 400)

    if page < 1 or per_page < 1:
        return error_response("page and per_page must be 1 or higher.", 400)

    if page > MAX_PAGE:
        return error_response(f"page must be {MAX_PAGE} or lower.", 400)

    # Stop people asking for a huge page that would slow the server down
    per_page = min(per_page, MAX_PER_PAGE)

    # Only the logged-in user's notes, newest first.
    # error_out=False means a page past the end gives an empty list
    # instead of a 404 error.
    pagination = (
        Note.query
        .filter_by(user_id=current_user.id)
        .order_by(Note.id.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    return {
        "notes": [note.to_dict() for note in pagination.items],
        "pagination": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total_notes": pagination.total,
            "total_pages": pagination.pages,
            "has_next": pagination.has_next,
            "has_previous": pagination.has_prev,
        },
    }, 200


@app.route("/notes/<int:note_id>", methods=["PATCH"])
@jwt_required()
def update_note(note_id):
    note = get_own_note(note_id)
    if note is None:
        return error_response("Note not found.", 404)

    data = get_json_body()
    if data is None:
        return error_response("Request body must be a JSON object.", 400)

    # PATCH only changes the fields that were sent. Anything else in the
    # body (id, user_id, created_at...) is ignored on purpose, so a user
    # cannot hand their note over to somebody else.
    fields_to_update = [field for field in ("title", "content") if field in data]
    if not fields_to_update:
        return error_response("Provide a title and/or content to update.", 400)

    errors = []
    clean = {}

    for field in fields_to_update:
        value, error = validate_note_field(field, data[field])
        if error:
            errors.append(error)
        else:
            clean[field] = value

    # Check everything first, then change the note. This way a bad title
    # cannot leave the note half updated.
    if errors:
        return error_response(errors, 400)

    for field, value in clean.items():
        setattr(note, field, value)

    db.session.commit()

    return note.to_dict(), 200


@app.route("/notes/<int:note_id>", methods=["DELETE"])
@jwt_required()
def delete_note(note_id):
    note = get_own_note(note_id)
    if note is None:
        return error_response("Note not found.", 404)

    db.session.delete(note)
    db.session.commit()

    return {"message": "Note deleted successfully."}, 200


if __name__ == "__main__":
    # Port 5555 matches the "proxy" setting in the React client's package.json.
    # Debug mode is off unless you set FLASK_DEBUG=1 (never use it in production).
    app.run(port=5555, debug=os.environ.get("FLASK_DEBUG") == "1")
