from flask import Blueprint
from flask_jwt_extended import create_access_token, current_user, jwt_required
from sqlalchemy.exc import IntegrityError

from errors import ApiError
from extensions import db
from models import User
from schemas import LoginSchema, SignupSchema, parse_request

auth_bp = Blueprint("auth", __name__)  # the Flask version of APIRouter


def auth_response(user, status):
    """Signup and login both return {token, user}, so build it once."""
    # identity must be TEXT, so str(user.id).
    token = create_access_token(identity=str(user.id))
    return {"token": token, "user": user.to_dict()}, status


@auth_bp.post("/signup")
def signup():
    data = parse_request(SignupSchema())

    # Friendly check first...
    if User.query.filter_by(username=data["username"]).first():
        raise ApiError("Username already exists.", 409)

    user = User(username=data["username"])
    user.password_hash = data["password"]  # the setter hashes it
    try:
        db.session.add(user)
        db.session.commit()
    except IntegrityError:
        # ...and a safety net: two people can sign up with the same name at the
        # same instant and both pass the check above. The database's unique
        # rule is the final judge.
        db.session.rollback()
        raise ApiError("Username already exists.", 409)

    return auth_response(user, 201)


@auth_bp.post("/login")
def login():
    data = parse_request(LoginSchema())
    user = User.query.filter_by(username=data["username"]).first()

    # ONE message for "no such user" and "wrong password", so an attacker
    # can't use login to discover which usernames exist.
    if user is None or not user.authenticate(data["password"]):
        raise ApiError("Invalid username or password.", 401)

    return auth_response(user, 200)


@auth_bp.get("/me")
@jwt_required()  # 401 unless a valid token is sent
def me():
    return current_user.to_dict(), 200