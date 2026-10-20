from flask import current_app, request
from marshmallow import EXCLUDE, Schema, ValidationError, fields, validate, validates_schema

from errors import ApiError
from models import (CONTENT_MAX, PASSWORD_MAX_BYTES, PASSWORD_MIN, TITLE_MAX,
                    USERNAME_MAX, USERNAME_MIN)


class TrimmedString(fields.String):
    """A String that strips spaces BEFORE the validators run, so "   " counts
    as empty. A custom field means we write this once, not in every schema."""

    def _deserialize(self, value, attr, data, **kwargs):
        # super() first: it rejects non-text (123, lists, None) with a clear error.
        return super()._deserialize(value, attr, data, **kwargs).strip()


def text_length(min_length, max_length):
    """One reusable length rule with a message people can understand.
    Because TrimmedString strips first, "   " fails the minimum too."""
    return validate.Length(
        min=min_length,
        max=max_length,
        error=f"Must be {min_length}-{max_length} characters (spaces alone do not count).",
    )


def validate_password(value):
    # Not trimmed (spaces can be part of a password), but all-spaces is rejected.
    if not value.strip():
        raise ValidationError("Password cannot be blank.")
    if len(value) < PASSWORD_MIN:
        raise ValidationError(f"Password must be at least {PASSWORD_MIN} characters.")
    # Bytes, not characters: "é" is 1 character but 2 bytes.
    if len(value.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise ValidationError(f"Password must be at most {PASSWORD_MAX_BYTES} bytes.")


class SignupSchema(Schema):
    class Meta:
        unknown = EXCLUDE  # ignore keys we didn't declare

    username = TrimmedString(required=True, validate=text_length(USERNAME_MIN, USERNAME_MAX))
    password = fields.String(required=True, validate=validate_password)
    password_confirmation = fields.String(required=True)

    @validates_schema
    def passwords_match(self, data, **kwargs):
        # Compares TWO fields, so it can't be a single-field validator.
        if data["password"] != data["password_confirmation"]:
            raise ValidationError("Passwords do not match.", "password_confirmation")


class LoginSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    username = TrimmedString(required=True, validate=validate.Length(min=1))
    # Only "not empty" here. Showing password RULES at login would help attackers.
    password = fields.String(required=True, validate=validate.Length(min=1))


class NoteSchema(Schema):
    class Meta:
        # Anything else is dropped, so a client can't send "user_id": 5
        # to create a note for someone else.
        unknown = EXCLUDE

    title = TrimmedString(required=True, validate=text_length(1, TITLE_MAX))
    content = TrimmedString(required=True, validate=text_length(1, CONTENT_MAX))


def flatten_errors(messages):
    """{"title": ["Missing data..."]} -> ["title: Missing data..."]
    (a flat list is what the React client displays)."""
    flat = []
    for field, problems in messages.items():
        for problem in problems:
            flat.append(problem if field == "_schema" else f"{field}: {problem}")
    return flat


def parse_request(schema, partial=False):
    """Read the JSON body and validate it. Every route that accepts a body
    uses this, so the checks exist ONCE. partial=True (PATCH) means
    'fields are optional, but any field sent must still be valid'."""
    max_bytes = current_app.config["MAX_CONTENT_LENGTH"]
    if request.content_length and request.content_length > max_bytes:
        raise ApiError("Request body is too large.", 413)

    # silent=True returns None instead of crashing on broken JSON, so WE
    # choose the error message. Lists, strings and numbers are rejected too.
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Request body must be a JSON object.", 400)

    try:
        return schema.load(data, partial=partial)
    except ValidationError as err:
        raise ApiError(flatten_errors(err.messages), 422)