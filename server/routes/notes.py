"""Protected CRUD endpoints for a user's private notes."""
from flask import Blueprint, current_app, request
from flask_jwt_extended import current_user, jwt_required

from helpers import (
    DEFAULT_PER_PAGE, MAX_PAGE, MAX_PER_PAGE, error_response,
    get_json_body, get_own_note, validate_note_field,
)
from models import db, Note

notes_bp = Blueprint("notes", __name__)


@notes_bp.route("/notes", methods=["GET", "POST"])
@jwt_required()
def notes_collection():
    if request.method == "POST":
        data = get_json_body(request)
        if data is None:
            return error_response("Request body must be a JSON object.", 400)
        errors, clean = [], {}
        for field in ("title", "content"):
            if field not in data:
                errors.append(f"{field.capitalize()} is required.")
                continue
            value, error = validate_note_field(field, data[field])
            if error:
                errors.append(error)
            else:
                clean[field] = value
        if errors:
            return error_response(errors, 400)

        note = Note(title=clean["title"], content=clean["content"], user_id=current_user.id)
        db.session.add(note)
        db.session.commit()
        return note.to_dict(), 201

    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", DEFAULT_PER_PAGE))
    except ValueError:
        return error_response("page and per_page must be whole numbers.", 400)
    if page < 1 or per_page < 1:
        return error_response("page and per_page must be 1 or higher.", 400)
    if page > MAX_PAGE:
        return error_response(f"page must be {MAX_PAGE} or lower.", 400)

    pagination = (
        Note.query.filter_by(user_id=current_user.id)
        .order_by(Note.id.desc())
        .paginate(page=page, per_page=min(per_page, MAX_PER_PAGE), error_out=False)
    )
    return {
        "notes": [note.to_dict() for note in pagination.items],
        "pagination": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total_notes": pagination.total,
            "total_pages": pagination.pages,
            "has_next": pagination.has_next,
            "has_previous": pagination.has_prev,
        },
    }, 200


@notes_bp.route("/notes/<int:note_id>", methods=["PATCH", "DELETE"])
@jwt_required()
def note_detail(note_id):
    note = get_own_note(note_id, current_user)
    if note is None:
        return error_response("Note not found.", 404)

    if request.method == "DELETE":
        db.session.delete(note)
        db.session.commit()
        return {"message": "Note deleted successfully."}, 200

    data = get_json_body(request)
    if data is None:
        return error_response("Request body must be a JSON object.", 400)
    fields = [field for field in ("title", "content") if field in data]
    if not fields:
        return error_response("Provide a title and/or content to update.", 400)
    errors, clean = [], {}
    for field in fields:
        value, error = validate_note_field(field, data[field])
        if error:
            errors.append(error)
        else:
            clean[field] = value
    if errors:
        return error_response(errors, 400)
    for field, value in clean.items():
        setattr(note, field, value)
    db.session.commit()
    return note.to_dict(), 200
