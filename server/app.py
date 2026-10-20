from flask import Flask

from config import Config
from errors import register_error_handlers
from extensions import bcrypt, db, jwt, migrate
import jwt_callbacks  # noqa: F401  (importing it registers the callbacks)
from routes.auth import auth_bp
from routes.notes import notes_bp


def create_app(config_object=Config):
    """Application factory: builds a fresh app each call, so tests can build
    one with TestConfig."""
    app = Flask(__name__)
    app.config.from_object(config_object)

    # Fail at startup with a clear message, not on the first login.
    if not app.config["JWT_SECRET_KEY"]:
        raise RuntimeError("JWT_SECRET_KEY is not set. Add it to server/.env.")

    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    jwt.init_app(app)

    register_error_handlers(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(notes_bp)

    @app.get("/")
    def home():
        return {"message": "Productivity API is running!"}

    return app


if __name__ == "__main__":
    # Port 5555 matches the "proxy" in the React package.json.
    create_app().run(port=5555, debug=True)