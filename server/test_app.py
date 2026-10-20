"""Automated tests for the Productivity API.

Run from the server/ folder with:   pytest -q
The tests use a temporary in-memory database, so your real data is never touched.
"""
import os
from datetime import timedelta

# These must be set BEFORE app.py is imported, because app.py reads them
# when it loads.
os.environ["JWT_SECRET_KEY"] = "test-secret-key"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from flask_jwt_extended import create_access_token

from app import app, bcrypt
from models import db, User, Note


@pytest.fixture
def client():
    """A test client with a fresh, empty database for every test."""
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def signup(client, username="alice", password="password123", confirmation=None):
    """Helper: register a user and return the response."""
    return client.post("/signup", json={
        "username": username,
        "password": password,
        "password_confirmation": password if confirmation is None else confirmation,
    })


def auth_header(client, username="alice"):
    """Helper: sign up a user and return their Authorization header."""
    token = signup(client, username).get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def add_note(client, headers, title="Title", content="Content"):
    return client.post("/notes", json={"title": title, "content": content}, headers=headers)


# ---------- Signup ----------

def test_signup_success_returns_token_and_user(client):
    response = signup(client)
    body = response.get_json()
    assert response.status_code == 201
    assert body["user"]["username"] == "alice"
    assert body["token"]
    assert "password" not in str(body)


def test_signup_stores_hashed_password(client):
    signup(client, password="password123")
    user = User.query.filter_by(username="alice").first()
    assert user.password_hash != "password123"
    assert bcrypt.check_password_hash(user.password_hash, "password123")


def test_signup_trims_username(client):
    assert signup(client, username="  alice  ").get_json()["user"]["username"] == "alice"


@pytest.mark.parametrize("username, password, confirmation", [
    ("", "password123", "password123"),          # missing username
    ("al", "password123", "password123"),        # username too short
    ("a" * 81, "password123", "password123"),    # username too long
    ("alice", "short", "short"),                 # password too short
    ("alice", "   ", "   "),                     # password only spaces
    ("alice", "password123", "different123"),    # passwords do not match
    ("alice", "password123", ""),                # missing confirmation
    ("alice", "é" * 40, "é" * 40),               # 80 bytes, over bcrypt's 72 limit
])
def test_signup_validation_errors(client, username, password, confirmation):
    response = signup(client, username, password, confirmation)
    assert response.status_code == 400
    assert response.get_json()["errors"]


def test_signup_reports_all_problems_at_once(client):
    response = signup(client, username="", password="short", confirmation="nope")
    assert len(response.get_json()["errors"]) == 3


def test_signup_rejects_non_text_values(client):
    response = client.post("/signup", json={
        "username": 123, "password": ["x"], "password_confirmation": None,
    })
    assert response.status_code == 400


def test_signup_rejects_bad_json(client):
    response = client.post("/signup", data="not json", content_type="application/json")
    assert response.status_code == 400
    response = client.post("/signup", json=["a", "list"])
    assert response.status_code == 400


def test_signup_duplicate_username_is_409_even_with_different_case(client):
    signup(client, "alice")
    assert signup(client, "alice").status_code == 409
    assert signup(client, "ALICE").status_code == 409


# ---------- Login and /me ----------

def test_login_success(client):
    signup(client)
    response = client.post("/login", json={"username": "alice", "password": "password123"})
    assert response.status_code == 200
    assert response.get_json()["token"]


def test_login_is_case_insensitive_for_username(client):
    signup(client)
    response = client.post("/login", json={"username": "ALICE", "password": "password123"})
    assert response.status_code == 200


def test_login_wrong_password_and_unknown_user_give_same_error(client):
    signup(client)
    wrong_pw = client.post("/login", json={"username": "alice", "password": "nope-nope"})
    no_user = client.post("/login", json={"username": "ghost", "password": "password123"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.get_json() == no_user.get_json()


def test_login_missing_or_bad_fields(client):
    assert client.post("/login", json={}).status_code == 400
    assert client.post("/login", json={"username": "alice"}).status_code == 400
    assert client.post("/login", json={"username": 1, "password": 2}).status_code == 400
    assert client.post("/login", data="oops", content_type="application/json").status_code == 400


def test_me_with_valid_token(client):
    headers = auth_header(client)
    response = client.get("/me", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["username"] == "alice"


def test_me_without_token_or_with_garbage_token_is_401(client):
    assert client.get("/me").status_code == 401
    # "Bearer null" is exactly what the React client sends when nobody is logged in
    assert client.get("/me", headers={"Authorization": "Bearer null"}).status_code == 401


def test_expired_token_is_401(client):
    signup(client)
    user = User.query.filter_by(username="alice").first()
    expired = create_access_token(identity=str(user.id), expires_delta=timedelta(seconds=-1))
    response = client.get("/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_token_of_deleted_user_is_401(client):
    headers = auth_header(client)
    db.session.delete(User.query.filter_by(username="alice").first())
    db.session.commit()
    assert client.get("/notes", headers=headers).status_code == 401


# ---------- Notes: authentication ----------

def test_every_notes_route_needs_a_token(client):
    assert client.get("/notes").status_code == 401
    assert client.post("/notes", json={"title": "a", "content": "b"}).status_code == 401
    assert client.patch("/notes/1", json={"title": "a"}).status_code == 401
    assert client.delete("/notes/1").status_code == 401


# ---------- Notes: create ----------

def test_create_note(client):
    headers = auth_header(client)
    response = add_note(client, headers, "  My title  ", "  My content  ")
    body = response.get_json()
    assert response.status_code == 201
    assert body["title"] == "My title"          # whitespace trimmed
    assert body["content"] == "My content"
    assert body["user_id"] == User.query.filter_by(username="alice").first().id


def test_create_note_ignores_user_id_sent_in_body(client):
    auth_header(client, "bob")
    alice_headers = auth_header(client, "alice")
    response = client.post(
        "/notes",
        json={"title": "t", "content": "c", "user_id": 1},
        headers=alice_headers,
    )
    alice = User.query.filter_by(username="alice").first()
    assert response.get_json()["user_id"] == alice.id


@pytest.mark.parametrize("payload", [
    {},                                          # nothing sent
    {"title": "Only a title"},                   # content missing
    {"content": "Only content"},                 # title missing
    {"title": "   ", "content": "x"},            # blank title
    {"title": "x", "content": ""},               # empty content
    {"title": 123, "content": "x"},              # wrong type
    {"title": "x" * 151, "content": "x"},        # title too long
    {"title": "x", "content": "x" * 5001},       # content too long
])
def test_create_note_validation_errors(client, payload):
    headers = auth_header(client)
    response = client.post("/notes", json=payload, headers=headers)
    assert response.status_code == 400
    assert response.get_json()["errors"]
    assert Note.query.count() == 0              # nothing was saved


def test_create_note_with_bad_json_body(client):
    headers = auth_header(client)
    response = client.post("/notes", data="nope", content_type="application/json", headers=headers)
    assert response.status_code == 400


# ---------- Notes: list and pagination ----------

def test_list_only_returns_own_notes_newest_first(client):
    alice = auth_header(client, "alice")
    bob = auth_header(client, "bob")
    add_note(client, alice, "first")
    add_note(client, alice, "second")
    add_note(client, bob, "bobs note")

    body = client.get("/notes", headers=alice).get_json()
    assert [n["title"] for n in body["notes"]] == ["second", "first"]
    assert body["pagination"]["total_notes"] == 2


def test_empty_list_for_new_user(client):
    body = client.get("/notes", headers=auth_header(client)).get_json()
    assert body["notes"] == []
    assert body["pagination"]["total_notes"] == 0


def test_pagination(client):
    headers = auth_header(client)
    for i in range(12):
        add_note(client, headers, f"note {i}")

    page1 = client.get("/notes", headers=headers).get_json()
    assert len(page1["notes"]) == 10
    assert page1["pagination"]["total_pages"] == 2
    assert page1["pagination"]["has_next"] is True
    assert page1["pagination"]["has_previous"] is False

    page2 = client.get("/notes?page=2", headers=headers).get_json()
    assert len(page2["notes"]) == 2
    assert page2["pagination"]["has_next"] is False
    assert page2["pagination"]["has_previous"] is True


def test_per_page_is_respected_and_capped(client):
    headers = auth_header(client)
    for i in range(3):
        add_note(client, headers, f"note {i}")
    assert len(client.get("/notes?per_page=2", headers=headers).get_json()["notes"]) == 2
    assert client.get("/notes?per_page=5000", headers=headers).get_json()["pagination"]["per_page"] == 100


def test_page_past_the_end_gives_empty_list(client):
    headers = auth_header(client)
    add_note(client, headers)
    response = client.get("/notes?page=99", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["notes"] == []


@pytest.mark.parametrize("query", [
    "page=0", "page=-1", "per_page=0", "page=abc", "per_page=1.5", "page=",
])
def test_bad_pagination_params_are_400(client, query):
    headers = auth_header(client)
    assert client.get(f"/notes?{query}", headers=headers).status_code == 400


def test_huge_page_number_does_not_crash(client):
    headers = auth_header(client)
    response = client.get("/notes?page=99999999999999999999999", headers=headers)
    assert response.status_code == 400


# ---------- Notes: update ----------

def test_update_title_only_keeps_content(client):
    headers = auth_header(client)
    note_id = add_note(client, headers, "old", "keep me").get_json()["id"]
    response = client.patch(f"/notes/{note_id}", json={"title": "new"}, headers=headers)
    body = response.get_json()
    assert response.status_code == 200
    assert body["title"] == "new"
    assert body["content"] == "keep me"


def test_update_cannot_change_owner_or_id(client):
    headers = auth_header(client)
    note = add_note(client, headers).get_json()
    client.patch(f"/notes/{note['id']}", json={"title": "x", "user_id": 999, "id": 999}, headers=headers)
    saved = db.session.get(Note, note["id"])
    assert saved.user_id == note["user_id"]
    assert saved.id == note["id"]


@pytest.mark.parametrize("payload", [
    {}, {"unknown": "field"}, {"title": ""}, {"content": "   "}, {"title": None}, {"title": 5},
])
def test_update_validation_errors(client, payload):
    headers = auth_header(client)
    note_id = add_note(client, headers, "keep", "keep").get_json()["id"]
    response = client.patch(f"/notes/{note_id}", json=payload, headers=headers)
    assert response.status_code == 400
    assert db.session.get(Note, note_id).title == "keep"


def test_update_with_one_bad_field_changes_nothing(client):
    headers = auth_header(client)
    note_id = add_note(client, headers, "keep", "keep").get_json()["id"]
    response = client.patch(f"/notes/{note_id}", json={"title": "changed", "content": ""}, headers=headers)
    assert response.status_code == 400
    assert db.session.get(Note, note_id).title == "keep"


def test_update_missing_note_is_404(client):
    headers = auth_header(client)
    assert client.patch("/notes/999", json={"title": "x"}, headers=headers).status_code == 404


def test_cannot_update_someone_elses_note(client):
    alice = auth_header(client, "alice")
    bob = auth_header(client, "bob")
    note_id = add_note(client, alice, "private").get_json()["id"]

    response = client.patch(f"/notes/{note_id}", json={"title": "hacked"}, headers=bob)
    assert response.status_code == 404
    assert db.session.get(Note, note_id).title == "private"


# ---------- Notes: delete ----------

def test_delete_note(client):
    headers = auth_header(client)
    note_id = add_note(client, headers).get_json()["id"]
    assert client.delete(f"/notes/{note_id}", headers=headers).status_code == 200
    assert db.session.get(Note, note_id) is None
    # deleting it a second time is a 404, not a crash
    assert client.delete(f"/notes/{note_id}", headers=headers).status_code == 404


def test_cannot_delete_someone_elses_note(client):
    alice = auth_header(client, "alice")
    bob = auth_header(client, "bob")
    note_id = add_note(client, alice).get_json()["id"]

    assert client.delete(f"/notes/{note_id}", headers=bob).status_code == 404
    assert db.session.get(Note, note_id) is not None


def test_deleting_a_user_deletes_their_notes(client):
    headers = auth_header(client)
    add_note(client, headers)
    db.session.delete(User.query.filter_by(username="alice").first())
    db.session.commit()
    assert Note.query.count() == 0


# ---------- Error handlers ----------

def test_unknown_route_returns_json_404(client):
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.get_json() == {"errors": ["Resource not found."]}


def test_wrong_method_returns_json_405(client):
    response = client.put("/notes")
    assert response.status_code == 405
    assert response.get_json()["errors"]


def test_non_numeric_note_id_is_404(client):
    headers = auth_header(client)
    assert client.delete("/notes/abc", headers=headers).status_code == 404


def test_huge_note_id_does_not_crash(client):
    headers = auth_header(client)
    response = client.delete("/notes/99999999999999999999999", headers=headers)
    assert response.status_code == 404


def test_oversized_body_is_413(client):
    response = client.post("/signup", data="x" * (1024 * 1024 + 10), content_type="application/json")
    assert response.status_code == 413
    assert response.get_json()["errors"]

