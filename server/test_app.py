"""Automated tests for the Productivity API.

Run from the server/ folder with:   pytest -q
Each test gets a brand-new in-memory database, so your real data is never touched.
"""
from datetime import timedelta

import pytest
from flask_jwt_extended import create_access_token

from app import create_app
from config import TestConfig
from extensions import db
from models import Note, User


@pytest.fixture
def client():
    """A test client with a fresh, empty database for every test."""
    app = create_app(TestConfig)  # TestConfig = in-memory DB + test secret key
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


# ---------- Helpers (written once, reused by many tests: DRY) ----------

def signup(client, username="alice", password="password123", confirmation=None):
    """Register a user and return the response."""
    return client.post("/signup", json={
        "username": username,
        "password": password,
        "password_confirmation": password if confirmation is None else confirmation,
    })


def auth_header(client, username="alice"):
    """Sign up a user and return their Authorization header."""
    token = signup(client, username).get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def add_note(client, headers, title="Title", content="Content"):
    return client.post("/notes", json={"title": title, "content": content}, headers=headers)


def assert_error(response, status):
    """Every failure must have the right status AND our {"errors": [...]} shape,
    so users are always told what went wrong."""
    assert response.status_code == status
    errors = response.get_json()["errors"]
    assert isinstance(errors, list) and errors


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
    assert user.authenticate("password123")       # the real password works
    assert not user.authenticate("wrong-password")
    assert "password123" not in user._password_hash  # only the hash is stored


def test_password_hash_cannot_be_read(client):
    signup(client)
    user = User.query.filter_by(username="alice").first()
    with pytest.raises(AttributeError):
        user.password_hash


def test_signup_trims_username(client):
    assert signup(client, username="  alice  ").get_json()["user"]["username"] == "alice"


@pytest.mark.parametrize("username, password, confirmation", [
    ("", "password123", "password123"),          # empty username
    ("   ", "password123", "password123"),       # username only spaces
    ("al", "password123", "password123"),        # username too short
    ("a" * 51, "password123", "password123"),    # username too long
    ("alice", "short", "short"),                 # password too short
    ("alice", "        ", "        "),           # password only spaces
    ("alice", "password123", "different123"),    # passwords do not match
    ("alice", "password123", ""),                # empty confirmation
    ("alice", "é" * 40, "é" * 40),               # 80 bytes, over bcrypt's 72 limit
])
def test_signup_validation_errors(client, username, password, confirmation):
    assert_error(signup(client, username, password, confirmation), 422)
    assert User.query.count() == 0               # nothing was saved


@pytest.mark.parametrize("payload", [
    {},                                          # nothing sent
    {"username": "alice"},                       # password fields missing
    {"username": 123, "password": ["x"], "password_confirmation": None},  # wrong types
])
def test_signup_missing_or_non_text_fields(client, payload):
    assert_error(client.post("/signup", json=payload), 422)


def test_signup_rejects_bad_json(client):
    assert_error(client.post("/signup", data="not json", content_type="application/json"), 400)
    assert_error(client.post("/signup", json=["a", "list"]), 400)


def test_signup_duplicate_username_is_409(client):
    signup(client, "alice")
    assert_error(signup(client, "alice"), 409)
    assert User.query.count() == 1


# ---------- Login and /me ----------

def test_login_success(client):
    signup(client)
    response = client.post("/login", json={"username": "alice", "password": "password123"})
    assert response.status_code == 200
    assert response.get_json()["token"]


def test_login_wrong_password_and_unknown_user_give_same_error(client):
    signup(client)
    wrong_pw = client.post("/login", json={"username": "alice", "password": "nope-nope"})
    no_user = client.post("/login", json={"username": "ghost", "password": "password123"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.get_json() == no_user.get_json()  # attacker learns nothing


def test_login_with_very_long_password_is_401_not_500(client):
    signup(client)
    assert_error(client.post("/login", json={"username": "alice", "password": "x" * 200}), 401)


@pytest.mark.parametrize("payload", [
    {}, {"username": "alice"}, {"username": 1, "password": 2},
])
def test_login_missing_or_bad_fields(client, payload):
    assert_error(client.post("/login", json=payload), 422)


def test_login_bad_json(client):
    assert_error(client.post("/login", data="oops", content_type="application/json"), 400)


def test_me_with_valid_token(client):
    response = client.get("/me", headers=auth_header(client))
    assert response.status_code == 200
    assert response.get_json()["username"] == "alice"


def test_me_without_token_or_with_garbage_token_is_401(client):
    assert_error(client.get("/me"), 401)
    # "Bearer null" is exactly what the React client sends when nobody is logged in
    assert_error(client.get("/me", headers={"Authorization": "Bearer null"}), 401)


def test_expired_token_is_401(client):
    signup(client)
    user = User.query.filter_by(username="alice").first()
    expired = create_access_token(identity=str(user.id), expires_delta=timedelta(seconds=-1))
    assert_error(client.get("/me", headers={"Authorization": f"Bearer {expired}"}), 401)


def test_token_of_deleted_user_is_401(client):
    headers = auth_header(client)
    db.session.delete(User.query.filter_by(username="alice").first())
    db.session.commit()
    assert_error(client.get("/notes", headers=headers), 401)


# ---------- Notes: authentication ----------

def test_every_notes_route_needs_a_token(client):
    assert_error(client.get("/notes"), 401)
    assert_error(client.post("/notes", json={"title": "a", "content": "b"}), 401)
    assert_error(client.patch("/notes/1", json={"title": "a"}), 401)
    assert_error(client.delete("/notes/1"), 401)


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
    bob_id = signup(client, "bob").get_json()["user"]["id"]
    alice_headers = auth_header(client, "alice")
    response = client.post(
        "/notes",
        json={"title": "t", "content": "c", "user_id": bob_id},
        headers=alice_headers,
    )
    alice = User.query.filter_by(username="alice").first()
    assert response.get_json()["user_id"] == alice.id != bob_id


@pytest.mark.parametrize("payload", [
    {},                                          # nothing sent
    {"title": "Only a title"},                   # content missing
    {"content": "Only content"},                 # title missing
    {"title": "   ", "content": "x"},            # blank title
    {"title": "x", "content": ""},               # empty content
    {"title": 123, "content": "x"},              # wrong type
    {"title": None, "content": "x"},             # null
    {"title": "x" * 151, "content": "x"},        # title too long
    {"title": "x", "content": "x" * 5001},       # content too long
])
def test_create_note_validation_errors(client, payload):
    response = client.post("/notes", json=payload, headers=auth_header(client))
    assert_error(response, 422)
    assert Note.query.count() == 0              # nothing was saved


def test_create_note_with_bad_json_body(client):
    response = client.post("/notes", data="nope", content_type="application/json",
                           headers=auth_header(client))
    assert_error(response, 400)


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
    # Asking for 5000 is allowed, but the response shows the real size used.
    assert client.get("/notes?per_page=5000", headers=headers).get_json()["pagination"]["per_page"] == 100


def test_page_past_the_end_gives_empty_list(client):
    headers = auth_header(client)
    add_note(client, headers)
    response = client.get("/notes?page=99", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["notes"] == []


@pytest.mark.parametrize("query", [
    "page=0", "page=-1", "per_page=0", "page=abc", "per_page=1.5", "page=",
    "page=99999999999999999999999",               # huge number must not crash
])
def test_bad_pagination_params_are_400(client, query):
    assert_error(client.get(f"/notes?{query}", headers=auth_header(client)), 400)


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


@pytest.mark.parametrize("payload, status", [
    ({}, 400),                       # nothing to update
    ({"unknown": "field"}, 400),     # only fields we ignore
    ({"title": ""}, 422),
    ({"content": "   "}, 422),
    ({"title": None}, 422),
    ({"title": 5}, 422),
])
def test_update_validation_errors(client, payload, status):
    headers = auth_header(client)
    note_id = add_note(client, headers, "keep", "keep").get_json()["id"]
    assert_error(client.patch(f"/notes/{note_id}", json=payload, headers=headers), status)
    assert db.session.get(Note, note_id).title == "keep"


def test_update_with_one_bad_field_changes_nothing(client):
    headers = auth_header(client)
    note_id = add_note(client, headers, "keep", "keep").get_json()["id"]
    response = client.patch(f"/notes/{note_id}", json={"title": "changed", "content": ""}, headers=headers)
    assert_error(response, 422)
    assert db.session.get(Note, note_id).title == "keep"   # even the good field was not applied


def test_update_with_bad_json_body(client):
    headers = auth_header(client)
    note_id = add_note(client, headers).get_json()["id"]
    response = client.patch(f"/notes/{note_id}", data="nope", content_type="application/json", headers=headers)
    assert_error(response, 400)


def test_update_missing_note_is_404(client):
    headers = auth_header(client)
    assert_error(client.patch("/notes/999", json={"title": "x"}, headers=headers), 404)


def test_cannot_update_someone_elses_note(client):
    alice = auth_header(client, "alice")
    bob = auth_header(client, "bob")
    note_id = add_note(client, alice, "private").get_json()["id"]

    assert_error(client.patch(f"/notes/{note_id}", json={"title": "hacked"}, headers=bob), 404)
    assert db.session.get(Note, note_id).title == "private"


# ---------- Notes: delete ----------

def test_delete_note(client):
    headers = auth_header(client)
    note_id = add_note(client, headers).get_json()["id"]
    assert client.delete(f"/notes/{note_id}", headers=headers).status_code == 200
    assert db.session.get(Note, note_id) is None
    # deleting it a second time is a 404, not a crash
    assert_error(client.delete(f"/notes/{note_id}", headers=headers), 404)


def test_cannot_delete_someone_elses_note(client):
    alice = auth_header(client, "alice")
    bob = auth_header(client, "bob")
    note_id = add_note(client, alice).get_json()["id"]

    assert_error(client.delete(f"/notes/{note_id}", headers=bob), 404)
    assert db.session.get(Note, note_id) is not None


def test_deleting_a_user_deletes_their_notes(client):
    headers = auth_header(client)
    add_note(client, headers)
    db.session.delete(User.query.filter_by(username="alice").first())
    db.session.commit()
    assert Note.query.count() == 0


# ---------- Error handlers ----------

def test_unknown_route_returns_json_404(client):
    assert_error(client.get("/nope"), 404)


def test_wrong_method_returns_json_405(client):
    assert_error(client.put("/notes", headers=auth_header(client)), 405)


def test_non_numeric_note_id_is_404(client):
    assert_error(client.delete("/notes/abc", headers=auth_header(client)), 404)


def test_huge_note_id_does_not_crash(client):
    response = client.delete("/notes/99999999999999999999999", headers=auth_header(client))
    assert_error(response, 404)


def test_oversized_body_is_413(client):
    response = client.post("/signup", data="x" * (1024 * 1024 + 10), content_type="application/json")
    assert_error(response, 413)


def test_unexpected_error_returns_json_500(client):
    """Force a crash to prove users get a clean JSON message, not a stack trace."""
    client.application.config["PROPAGATE_EXCEPTIONS"] = False

    @client.application.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    response = client.get("/boom")
    assert_error(response, 500)
    assert "secret internal detail" not in response.get_data(as_text=True)