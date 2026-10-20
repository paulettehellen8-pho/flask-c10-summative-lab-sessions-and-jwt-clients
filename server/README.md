# Productivity Tool API — Flask + JWT

A Flask REST API for a personal productivity tool. Users can create accounts, log in, check their identity with a JWT, and manage their own private notes. The backend uses SQLAlchemy, Flask-Migrate, Flask-Bcrypt, Flask-JWT-Extended, and a React client.

## Features

- Signup and login with hashed passwords (bcrypt); usernames are unique and checked case-insensitively.
- `GET /me` validates the bearer token and returns the current user.
- Protected notes CRUD: create, list, update, and delete.
- Notes belong to the authenticated user. A user cannot read, update, delete, or create notes for another user.
- Paginated note listing (`page`, `per_page`) with a default page size of 10 and maximum of 100.
- Consistent JSON error responses, request validation, and one-hour access tokens.
- Database migrations, repeatable seed data, and automated tests.

## Project structure

```text
server/
├── app.py                 # App factory, extension setup, error handling
├── extensions.py          # Shared Flask extension instances
├── models.py              # User and Note SQLAlchemy models
├── helpers.py             # Validation, response helpers, ownership lookup
├── routes/
│   ├── __init__.py
│   ├── auth.py            # Signup, login, /me
│   └── notes.py           # Protected notes CRUD and pagination
├── migrations/             # Flask-Migrate / Alembic migrations
├── seed.py                # Sample users and notes
├── test_app.py             # Pytest tests
├── Pipfile
├── Pipfile.lock
├── .env.example
└── README.md
client-with-jwt/            # Provided React JWT client
```

## Setup

Requirements: Python 3.12 and Pipenv.

1. Change into the backend directory:

   ```bash
   cd server
   ```

2. Install dependencies:

   ```bash
   pipenv install
   ```

3. Create a local environment file and set a strong secret:

   ```bash
   cp .env.example .env
   ```

   Edit `.env` and replace `JWT_SECRET_KEY` with a long random secret. Do not commit `.env`.

4. Apply the database migrations and seed sample data:

   ```bash
   pipenv run flask --app app db upgrade
   pipenv run python seed.py
   ```

5. Start the API:

   ```bash
   pipenv run python app.py
   ```

The API runs at `http://localhost:5555`. The React client uses this port as its development proxy target.

## Demo account

The seed script creates `alice` and `bob`, each with sample notes. Both accounts use the demo password `Password123!`. The script is safe to run repeatedly: it only creates a demo user if missing and only adds notes when that user has none.

## Authentication

Send the access token returned by signup or login as a bearer token on protected requests:

```http
Authorization: Bearer <token>
```

Tokens expire after one hour. JWT authentication is stateless; there is no server-side session logout endpoint. To log out in the frontend, discard the token locally. For a production system that needs immediate token revocation, add a token blocklist.

## API endpoints

All request and response bodies are JSON unless the response is `204` (not used by the current JWT API). Errors use this shape:

```json
{"errors": ["Explanation of the problem."]}
```

| Method | Endpoint | Auth | Purpose |
|---|---|---|---|
| `GET` | `/` | No | Health check |
| `POST` | `/signup` | No | Create account and return token + user |
| `POST` | `/login` | No | Authenticate and return token + user |
| `GET` | `/me` | Bearer token | Validate token and return current user |
| `POST` | `/notes` | Bearer token | Create a note |
| `GET` | `/notes?page=1&per_page=10` | Bearer token | List own notes with pagination |
| `PATCH` | `/notes/<id>` | Bearer token | Update title and/or content |
| `DELETE` | `/notes/<id>` | Bearer token | Delete a note |

### Signup example

```json
{
  "username": "newuser",
  "password": "password123",
  "password_confirmation": "password123"
}
```

Successful signup returns `201` with `{"token": "...", "user": {"id": 1, "username": "newuser"}}`.

### Note example

```json
{
  "title": "Finish assignment",
  "content": "Review the rubric and submit the project."
}
```

A note includes `id`, `title`, `content`, `created_at`, and `user_id`. The server always derives `user_id` from the token, never from the request body.

### Pagination response

`GET /notes` returns a `notes` array and a `pagination` object with `page`, `per_page`, `total_notes`, `total_pages`, `has_next`, and `has_previous`. Invalid page values return `400`. Notes are returned newest first.

## Tests

Run from `server/`:

```bash
pipenv run pytest -q
```

The tests use an in-memory SQLite database. They cover authentication, password hashing, note validation, pagination, ownership, and CRUD behavior.

## Security and design notes

- Passwords are stored only as bcrypt hashes.
- Usernames are unique at the database level and looked up case-insensitively by the API.
- Every notes endpoint requires a valid JWT.
- Queries are scoped to `current_user.id`; notes owned by another user are reported as not found.
- `.env` is ignored by Git. Configure a unique `JWT_SECRET_KEY` outside source control.
- `helpers.py` keeps validation and ownership logic reusable; blueprints separate authentication from note resources.
