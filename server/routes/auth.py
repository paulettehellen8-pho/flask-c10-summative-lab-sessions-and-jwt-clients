"""Signup, login, and current-user endpoints."""
from flask import Blueprint, current_app, request
from flask_jwt_extended import create_access_token, current_user, jwt_required
from sqlalchemy.exc import IntegrityError

from extensions import bcrypt
from helpers import (
    MAX_PASSWORD_BYTES, MAX_USERNAME_LENGTH, MIN_PASSWORD_LENGTH,
    MIN_USERNAME_LENGTH, error_response, find_user_by_username,
    get_json_body, is_text,
)
from models import db, User

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/signup")
def signup():
    data = get_json_body(request)
    if data is None:
        return error_response("Request body must be a JSON object.", 400)

    username = data.get("username", "")
    password = data.get("password", "")
    confirmation = data.get("password_confirmation", "")
    if not all(is_text(value) for value in (username, password, confirmation)):
        return error_response(
            "Username, password and password_confirmation must be text.", 400
        )

    username = username.strip()
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
        errors.append(f"Password must be at most {MAX_PASSWORD_BYTES} bytes long.")
    if not confirmation:
        errors.append("Password confirmation is required.")
    elif password != confirmation:
        errors.append("Passwords do not match.")
    if errors:
        return error_response(errors, 400)
    if find_user_by_username(username):
        return error_response("Username already exists.", 409)

    new_user = User(
        username=username,
        password_hash=bcrypt.generate_password_hash(password).decode("utf-8"),
    )
    try:
        db.session.add(new_user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error_response("Username already exists.", 409)

    token = create_access_token(identity=str(new_user.id))
    return {"token": token, "user": new_user.to_dict()}, 201


@auth_bp.post("/login")
def login():
    data = get_json_body(request)
    if data is None:
        return error_response("Request body must be a JSON object.", 400)
    username, password = data.get("username", ""), data.get("password", "")
    if not (is_text(username) and is_text(password)):
        return error_response("Username and password must be text.", 400)
    username = username.strip()
    if not username or not password:
        return error_response("Username and password are required.", 400)

    user = find_user_by_username(username)
    if user is None or not bcrypt.check_password_hash(user.password_hash, password):
        return error_response("Invalid username or password.", 401)

    token = create_access_token(identity=str(user.id))
    return {"token": token, "user": user.to_dict()}, 200


@auth_bp.get("/me")
@jwt_required()
def me():
    """Return the account represented by the bearer token."""
    return current_user.to_dict(), 200
