
import sys
from pathlib import Path

# Ensure the project root is importable when this script is executed.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Webhook
from app.security.webhook_secrets import (
    ENCRYPTED_PREFIX,
    encrypt_webhook_secret,
    decrypt_webhook_secret,
)


def main() -> None:
    encrypted_count = 0
    skipped_count = 0

    db = SessionLocal()

    try:
        with db.begin():
            webhooks = db.scalars(
                select(Webhook)
                .where(Webhook.secret.is_not(None))
                .with_for_update()
            ).all()

            for webhook in webhooks:
                original_secret = webhook.secret

                if not original_secret:
                    skipped_count += 1
                    continue

                if original_secret.startswith(ENCRYPTED_PREFIX):
                    skipped_count += 1
                    continue

                encrypted_secret = encrypt_webhook_secret(
                    original_secret
                )

                # Verify the encrypted value before saving.
                recovered_secret = decrypt_webhook_secret(
                    encrypted_secret
                )

                if recovered_secret != original_secret:
                    raise RuntimeError(
                        f"Secret verification failed for webhook "
                        f"{webhook.id}"
                    )

                webhook.secret = encrypted_secret
                encrypted_count += 1

        print("Webhook secret encryption completed.")
        print(f"Encrypted secrets: {encrypted_count}")
        print(f"Already encrypted or empty: {skipped_count}")

    except Exception:
        db.rollback()
        print(
            "Encryption failed. Database transaction rolled back."
        )
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()
