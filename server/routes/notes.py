from flask import Blueprint, request
from flask_jwt_extended import current_user, jwt_required

from errors import ApiError
from extensions import db
from models import Note
from schemas import NoteSchema, parse_request

DEFAULT_PER_PAGE = 10
MAX_PER_PAGE = 100
MAX_PAGE = 1_000_000          # a larger OFFSET can overflow the database
MAX_DB_INTEGER = 2**63 - 1    # the biggest id SQLite can store

notes_bp = Blueprint("notes", __name__, url_prefix="/notes")


@notes_bp.before_request
@jwt_required()
def require_login():
    """Runs before EVERY route in this blueprint. It's the Flask version of
    dependencies=[Depends(get_current_member)] in your FastAPI app.py:
    protect once, so no route can forget it."""


def get_page_args():
    # We do NOT use request.args.get("page", 1, type=int): on bad input it
    # silently falls back to the default, so ?page=abc would "work" and
    # hide the mistake. We want the user told.
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", DEFAULT_PER_PAGE))
    except ValueError:
        raise ApiError("page and per_page must be whole numbers.", 400)
    if page < 1 or per_page < 1:
        raise ApiError("page and per_page must be 1 or higher.", 400)
    if page > MAX_PAGE:
        raise ApiError(f"page must be {MAX_PAGE} or lower.", 400)
    # Capped silently, but the response includes the real per_page used.
    return page, min(per_page, MAX_PER_PAGE)


def get_own_note_or_404(note_id):
    """Used by PATCH and DELETE (DRY). Someone else's note gives the SAME 404
    as a missing one, so users can't discover which ids exist."""
    note = None
    if note_id <= MAX_DB_INTEGER:  # an oversized id would crash SQLite
        note = Note.query.filter_by(id=note_id, user_id=current_user.id).first()
    if note is None:
        raise ApiError("Note not found.", 404)
    return note


@notes_bp.get("")
def list_notes():
    page, per_page = get_page_args()
    pagination = (
        Note.query.filter_by(user_id=current_user.id)  # only MY notes
        .order_by(Note.id.desc())                      # newest first
        .paginate(page=page, per_page=per_page, error_out=False)  # past the end -> empty list, not 404
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


@notes_bp.post("")
def create_note():
    data = parse_request(NoteSchema())
    # user_id comes from the TOKEN, never from the request body.
    note = Note(user_id=current_user.id, **data)
    db.session.add(note)
    db.session.commit()
    return note.to_dict(), 201


@notes_bp.patch("/<int:note_id>")
def update_note(note_id):
    note = get_own_note_or_404(note_id)  # 404 check first
    data = parse_request(NoteSchema(), partial=True)
    if not data:
        # partial=True accepts {}, which would "succeed" while changing
        # nothing. Tell the user instead.
        raise ApiError("Provide a title and/or content to update.", 400)
    for field, value in data.items():
        setattr(note, field, value)
    db.session.commit()
    return note.to_dict(), 200


@notes_bp.delete("/<int:note_id>")
def delete_note(note_id):
    note = get_own_note_or_404(note_id)
    db.session.delete(note)
    db.session.commit()
    return {"message": "Note deleted successfully."}, 200