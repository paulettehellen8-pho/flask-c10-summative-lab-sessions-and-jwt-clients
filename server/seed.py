"""Fill the database with sample users and notes.

Run it AFTER the migrations:   python seed.py
It is safe to run more than once: users and notes that already exist are
not created again.
"""
from faker import Faker
from sqlalchemy.exc import OperationalError

from app import app, bcrypt
from models import db, User, Note

SAMPLE_PASSWORD = "Password123!"

# username -> how many notes to create. Alice gets 12 so that the default
# page size (10) gives two pages and pagination can be tried straight away.
SAMPLE_USERS = {"alice": 12, "bob": 3}

fake = Faker()
Faker.seed(42)  # same fake text every run, which makes demos repeatable


def seed_database():
    with app.app_context():
        try:
            for username, note_count in SAMPLE_USERS.items():
                user = User.query.filter_by(username=username).first()

                # Only create the user if they are not in the database yet
                if user is None:
                    user = User(
                        username=username,
                        password_hash=bcrypt.generate_password_hash(
                            SAMPLE_PASSWORD
                        ).decode("utf-8"),
                    )
                    db.session.add(user)
                    # flush() gives the new user an id without committing,
                    # and we need that id for the notes below.
                    db.session.flush()

                # Only add notes if this user has none yet
                if not user.notes:
                    for _ in range(note_count):
                        db.session.add(
                            Note(
                                title=fake.sentence(nb_words=4).rstrip("."),
                                content=fake.paragraph(nb_sentences=3),
                                user_id=user.id,
                            )
                        )

            db.session.commit()
        except OperationalError:
            # Usually means the tables do not exist yet
            db.session.rollback()
            print("Could not write to the database. Did you run 'flask db upgrade' first?")
            return

        print("Database seeded successfully!")
        print(f"Sample users: {', '.join(SAMPLE_USERS)}  |  password: {SAMPLE_PASSWORD}")


if __name__ == "__main__":
    seed_database()
