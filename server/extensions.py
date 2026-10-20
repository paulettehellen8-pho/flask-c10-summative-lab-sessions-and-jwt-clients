"""Extension objects are created here, unattached to any app. app.py attaches
them later with init_app(). This avoids circular imports: models.py can
import db without importing app.py."""
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate = Migrate()
bcrypt = Bcrypt()
jwt = JWTManager()