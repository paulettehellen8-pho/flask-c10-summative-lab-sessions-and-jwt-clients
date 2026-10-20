from datetime import datetime, timezone

from extensions import bcrypt, db

# Limits live HERE, once. The database column sizes and the validation rules
# in schemas.py both read these, so they can never disagree (DRY).
USERNAME_MIN, USERNAME_MAX = 3, 50
PASSWORD_MIN, PASSWORD_MAX_BYTES = 8, 72  # bcrypt cannot hash more than 72 bytes
TITLE_MAX = 150
CONTENT_MAX = 5000


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(USERNAME_MAX), unique=True, nullable=False)
    _password_hash = db.Column(db.String(128), nullable=False)  # underscore = private

    # If a user is deleted, their notes go too (no orphaned notes).
    notes = db.relationship("Note", back_populates="user", cascade="all, delete-orphan")

    @property
    def password_hash(self):
        # Reading the hash is blocked so it can't leak into a response.
        raise AttributeError("Password hashes are not readable.")

    @password_hash.setter
    def password_hash(self, password):
        # user.password_hash = "secret" hashes it automatically.
        self._password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def authenticate(self, password):
        # bcrypt 5 raises an error for passwords over 72 bytes. Without this
        # guard, a long password at LOGIN would crash with a 500.
        if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
            return False
        return bcrypt.check_password_hash(self._password_hash, password)

    def to_dict(self):
        return {"id": self.id, "username": self.username}


class Note(db.Model):
    __tablename__ = "notes"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(TITLE_MAX), nullable=False)
    content = db.Column(db.Text, nullable=False)
    # A lambda so the time is read when each note is created,
    # not once when the file is loaded.
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    # index=True speeds up "all notes for this user".
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    user = db.relationship("User", back_populates="notes")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
            "user_id": self.user_id,
        }