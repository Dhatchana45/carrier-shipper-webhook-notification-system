
from getpass import getpass
from sqlalchemy import select, or_
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models import User
from app.auth_service import hash_password


def main():
    username = input("Admin username: ").strip()
    email = input("Admin email: ").strip().lower()
    password = getpass("Admin password: ")
    confirm = getpass("Confirm password: ")

    if len(username) < 3:
        raise SystemExit("Username must contain at least 3 characters.")

    if "@" not in email:
        raise SystemExit("Enter a valid email address.")

    if password != confirm:
        raise SystemExit("Passwords do not match.")

    if len(password) < 8 or len(password.encode("utf-8")) > 72:
        raise SystemExit("Password must be 8–72 UTF-8 bytes.")

    db = SessionLocal()

    try:
        existing = db.scalar(
            select(User).where(
                or_(
                    User.username == username,
                    User.email == email,
                )
            )
        )

        if existing:
            raise SystemExit("Username or email already exists.")

        admin = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            role="admin",
            is_active=True,
            carrier_id=None,
            shipper_id=None,
        )

        db.add(admin)
        db.commit()
        db.refresh(admin)

        print("\nAdmin account created successfully.")
        print("Username:", admin.username)
        print("Email:", admin.email)
        print("Role:", admin.role)
        print("Active:", admin.is_active)

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()
