"""Shared Flask extensions, initialized by create_app()."""
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate

bcrypt = Bcrypt()
jwt = JWTManager()
migrate = Migrate()
