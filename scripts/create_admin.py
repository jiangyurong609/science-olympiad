import argparse
from sqlalchemy import select
from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.models.entities import User


def main():
    parser = argparse.ArgumentParser(description="Create an invitation/bootstrap administrator")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        email = args.email.lower()
        if db.scalar(select(User).where(User.email == email)):
            raise SystemExit("User already exists")
        db.add(User(email=email, full_name=args.name, password_hash=hash_password(args.password), role="admin"))
        db.commit()
    print(f"Created administrator {email}")


if __name__ == "__main__":
    main()
