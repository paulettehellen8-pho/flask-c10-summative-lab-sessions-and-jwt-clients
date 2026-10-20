import os
from datetime import timedelta

from dotenv import load_dotenv

# Copies the key=value lines in server/.env into os.environ

load_dotenv()


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///productivity.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False  # turns off a feature we don't use

    # No fallback value on purpose: a hard-coded secret in source code would
    # let anyone who reads the repo forge tokens. create_app() fails loudly
    # if this is missing.
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)

    MAX_CONTENT_LENGTH = 1024 * 1024  # 1 MB request body limit


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"  # throwaway DB for tests
    JWT_SECRET_KEY = "test-only-secret-that-is-at-least-32-bytes"