import sys
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import Config  # noqa: E402
from src.database import SessionLocal  # noqa: E402
from src.models import User  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        hashed = generate_password_hash(Config.SUPER_ADMIN_PASSWORD)
        user = db.query(User).filter_by(username=Config.SUPER_ADMIN_USERNAME).first()
        if user:
            updated = False
            if user.role != 'admin':
                user.role = 'admin'
                updated = True
            if user.email != Config.SUPER_ADMIN_EMAIL:
                user.email = Config.SUPER_ADMIN_EMAIL
                updated = True
            if not user.passwordHash or not check_password_hash(user.passwordHash, Config.SUPER_ADMIN_PASSWORD):
                user.passwordHash = hashed
                updated = True
            if updated:
                db.commit()
                print("Super admin refreshed.")
            else:
                print("Super admin already up to date.")
            return

        super_admin = User(
            username=Config.SUPER_ADMIN_USERNAME,
            email=Config.SUPER_ADMIN_EMAIL,
            passwordHash=hashed,
            role='admin',
        )
        db.add(super_admin)
        db.commit()
        print(f"Super admin '{Config.SUPER_ADMIN_USERNAME}' created.")
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

