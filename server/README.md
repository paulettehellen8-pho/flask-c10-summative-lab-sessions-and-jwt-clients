# Productivity API (Flask + JWT)

A REST API where users sign up, log in and manage their own private notes.

- Authentication uses **JWT** (Flask-JWT-Extended)
- Passwords are hashed with **bcrypt** (Flask-Bcrypt), never stored as plain text
- Data is stored in **SQLite** using SQLAlchemy, with **Flask-Migrate** for migrations
- Users can only see, edit and delete **their own** notes
- The notes list is **paginated**
- Built to work with the `client-with-jwt` React app in this repo

## Requirements

- Python 3.12
- [Pipenv](https://pipenv.pypa.io/) (`pip install pipenv`)

## Installation

All commands are run from the `server/` folder.

```bash
cd server
pipenv install
pipenv shell
```

Create your `.env` file. It holds the secret key used to sign tokens and is
not committed to git.

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

Open `.env` and paste the generated value after `JWT_SECRET_KEY=`.

Create the database tables and add the sample data:

```bash
flask db upgrade
python seed.py
```

The seed script creates two users, `alice` (12 notes) and `bob` (3 notes).
Both have the password `Password123!`. It is safe to run more than once.

## Running the app

```bash
python app.py
```

The API runs at http://localhost:5555.

To use it with the React client:

```bash
cd ../client-with-jwt
npm install
npm start          # opens http://localhost:4000
```

## Running the tests (optional)

```bash
pytest -q
```

The tests use a temporary in-memory database, so your real data is not touched.

## Authentication

`/signup` and `/login` return a token. Send it on every protected request:

```
Authorization: Bearer <token>
```

Tokens expire after 1 hour. A missing, invalid or expired token returns `401`.
Logging out is done by the client deleting its token.

## Endpoints

| Method | Route | Auth | Description |
|---|---|---|---|
| GET | `/` | No | Check that the API is running |
| POST | `/signup` | No | Create an account and return a token |
| POST | `/login` | No | Log in and return a token |
| GET | `/me` | Yes | Get the logged-in user |
| GET | `/notes?page=1&per_page=10` | Yes | List your notes, newest first (paginated) |
| POST | `/notes` | Yes | Create a note |
| PATCH | `/notes/<id>` | Yes | Update the title and/or content of your note |
| DELETE | `/notes/<id>` | Yes | Delete your note |

### POST /signup

```json
{ "username": "alice", "password": "Password123!", "password_confirmation": "Password123!" }
```

Returns `201`:

```json
{ "token": "<JWT>", "user": { "id": 1, "username": "alice" } }
```

Rules: username 3-80 characters (spaces around it are removed, and it is not
case sensitive); password at least 8 characters and at most 72 bytes (a bcrypt
limit); both passwords must match.
Returns `400` for invalid input and `409` if the username is taken.

### POST /login

```json
{ "username": "alice", "password": "Password123!" }
```

Returns `200` with the same body as signup. Returns `400` if a field is
missing, and `401` for a wrong username or password (the same message for
both, so nobody can discover which usernames exist).

### GET /me

Returns `200`: `{ "id": 1, "username": "alice" }`

### GET /notes

Query parameters: `page` (default 1) and `per_page` (default 10, maximum 100).

Returns `200`:

```json
{
  "notes": [
    { "id": 1, "title": "Buy milk", "content": "2 litres",
      "created_at": "2026-10-20T11:31:01.890757", "user_id": 1 }
  ],
  "pagination": {
    "page": 1, "per_page": 10, "total_notes": 1,
    "total_pages": 1, "has_next": false, "has_previous": false
  }
}
```

A page past the end returns an empty `notes` list. A `page` or `per_page`
that is not a whole number of 1 or more returns `400`.

### POST /notes

```json
{ "title": "Buy milk", "content": "2 litres" }
```

Returns `201` with the new note. Title (max 150 characters) and content (max
5000 characters) are required and cannot be blank. The note always belongs to
the logged-in user.

### PATCH /notes/&lt;id&gt;

Send `title`, `content` or both. Fields you leave out stay the same. Returns
`200` with the updated note, `400` for invalid or empty input, or `404` if the
note does not exist or belongs to someone else.

### DELETE /notes/&lt;id&gt;

Returns `200`: `{ "message": "Note deleted successfully." }`, or `404` if the
note does not exist or belongs to someone else.

## Errors

Every error uses the same JSON shape:

```json
{ "errors": ["Title cannot be empty.", "Content is required."] }
```

| Status | Meaning |
|---|---|
| 400 | Invalid input (missing or wrong fields, bad JSON, bad page number) |
| 401 | Missing, invalid or expired token, or wrong login details |
| 404 | Route not found, or note not found / not yours |
| 405 | Wrong HTTP method for the route |
| 409 | Username already taken |
| 413 | Request body larger than 1 MB |
| 500 | Unexpected server error |

## Project structure

```
server/
├── app.py            # Flask app, auth and notes routes, error handlers
├── models.py         # User and Note models
├── seed.py           # Sample data
├── test_app.py       # Automated tests (optional)
├── migrations/       # Flask-Migrate files
├── Pipfile           # Dependencies
├── .env.example      # Template for the .env file
└── README.md
```

## Security notes

- A note that belongs to another user returns `404`, the same as a note that
  does not exist, so ids cannot be guessed to find out what exists.
- The note owner is always taken from the token, never from the request body.
- The secret key is read from `.env`. The app refuses to start without it.