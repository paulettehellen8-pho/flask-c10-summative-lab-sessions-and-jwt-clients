"""Flask-JWT-Extended's default errors aren't in our {"errors": [...]} shape.
Each function below replaces one default."""
from errors import error_response
from extensions import db, jwt
from models import User


@jwt.user_lookup_loader
def load_user(jwt_header, jwt_data):
    """Runs on every protected request. Turns the token into a User object,
    which is what makes `current_user` work in the routes."""
    try:
        # The token stores the id as TEXT (newer JWT libraries require it).
        return db.session.get(User, int(jwt_data["sub"]))
    except (TypeError, ValueError):
        return None  # unreadable id -> treated like "user not found"


@jwt.user_lookup_error_loader
def user_not_found(jwt_header, jwt_data):
    # Valid token, but the account was deleted afterwards.
    return error_response("User no longer exists. Please log in again.", 401)


@jwt.unauthorized_loader
def missing_token(reason):
    return error_response("Authorization token is missing.", 401)


@jwt.invalid_token_loader
def invalid_token(reason):
    # The React client sends "Bearer null" when nobody is logged in; that lands here.
    return error_response("Authorization token is invalid.", 401)


@jwt.expired_token_loader
def expired_token(jwt_header, jwt_data):
    return error_response("Authorization token has expired. Please log in again.", 401)