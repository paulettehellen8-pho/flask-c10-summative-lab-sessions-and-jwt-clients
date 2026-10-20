"""Database models for the Productivity API.

Two tables:
  users - people who can log in
  notes - private notes, each one belongs to exactly one user
"""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utc_now():
    """Current time in UTC. Used as the default value for created_at."""
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    # unique=True stops two users sharing a username at the database level
    username = db.Column(db.String(80), unique=True, nullable=False)
    # We only ever store the bcrypt hash, never the real password
    password_hash = db.Column(db.String(128), nullable=False)

    # One user has many notes. If a user is deleted, their notes go too
    # (otherwise we would be left with notes that belong to nobody).
    notes = db.relationship(
        "Note",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def to_dict(self):
        """Safe version of the user to send as JSON (no password hash!)."""
        return {"id": self.id, "username": self.username}

    def __repr__(self):
        return f"<User {self.id} {self.username}>"


class Note(db.Model):
    __tablename__ = "notes"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    # Foreign key linking the note to its owner. index=True makes the
    # "give me all notes for this user" query fast.
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    user = db.relationship("User", back_populates="notes")

    def to_dict(self):
        """Turn the note into a dictionary that Flask can send as JSON."""
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
            "user_id": self.user_id,
        }

    def __repr__(self):
        return f"<Note {self.id} {self.title}>"
