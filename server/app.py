"""Application factory and Flask CLI entry point."""
import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, abort, request
from flask_cors import CORS
from flask_jwt_extended import current_user
from werkzeug.exceptions import HTTPException

from extensions import bcrypt, jwt, migrate
from helpers import MAX_BODY_BYTES, error_response
from models import db, User
from routes.auth import auth_bp
from routes.notes import notes_bp

load_dotenv()

ERROR_MESSAGES = {
    404: "Resource not found.",
    405: "Method not allowed for this URL.",
    413: "Request body is too large.",
    500: "Something went wrong on the server.",
}


def create_app(test_config=None):
    app = Flask(__name__)
    secret_key = os.environ.get("JWT_SECRET_KEY")
    if not secret_key and not (test_config and test_config.get("TESTING")):
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Copy .env.example to .env and set it "
            "(see the README)."
        )

    app.config.update(
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///productivity.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY=secret_key or "test-only-secret",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=1),
        MAX_CONTENT_LENGTH=MAX_BODY_BYTES,
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)
    migrate.init_app(app, db)

    # React's package.json proxy handles local development; CORS supports direct calls.
    CORS(app, origins=["http://localhost:4000"])

    @jwt.user_lookup_loader
    def load_user(jwt_header, jwt_data):
        try:
            return db.session.get(User, int(jwt_data["sub"]))
        except (TypeError, ValueError):
            return None

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

    @app.before_request
    def reject_large_requests():
        if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
            abort(413)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 500:
            db.session.rollback()
        return error_response(ERROR_MESSAGES.get(error.code, error.description), error.code)

    @app.get("/")
    def home():
        return {"message": "Productivity API is running!"}

    app.register_blueprint(auth_bp)
    app.register_blueprint(notes_bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(port=5555, debug=os.environ.get("FLASK_DEBUG") == "1")
