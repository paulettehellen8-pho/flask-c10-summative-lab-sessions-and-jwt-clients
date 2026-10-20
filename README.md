# Productivity Tool — Refactored Flask JWT Project

This repository pairs the supplied React JWT client with a Flask REST API.

- `server/` contains the backend, database models, migrations, seed script, and tests.
- `client-with-jwt/` contains the React frontend.
- Authentication is JWT-based. The React app sends `Authorization: Bearer <token>` for protected requests.

## Start the backend

```bash
cd server
pipenv install
cp .env.example .env
```

Edit `server/.env` and set `JWT_SECRET_KEY` to a strong random secret. Then run:

```bash
pipenv run flask --app app db upgrade
pipenv run python seed.py
pipenv run python app.py
```

The API listens on `http://localhost:5555`.

## Start the frontend

In another terminal:

```bash
cd client-with-jwt
npm install
npm start
```

## Run backend tests

From `server/`:

```bash
pipenv run pytest -q
```

See [`server/README.md`](server/README.md) for the endpoint reference, sample credentials, pagination details, and security notes.
