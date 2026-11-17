
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


ENCRYPTED_PREFIX = "fernet:v1:"


def _get_fernet() -> Fernet:
    key = settings.webhook_encryption_key

    if not key:
        raise RuntimeError(
            "WEBHOOK_ENCRYPTION_KEY is not configured."
        )

    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "WEBHOOK_ENCRYPTION_KEY is invalid. "
            "It must be a valid Fernet key."
        ) from exc


def encrypt_webhook_secret(secret: str | None) -> str | None:
    """Encrypt a webhook secret before storing it in the database."""

    if secret is None:
        return None

    if not secret:
        return secret

    # Avoid accidentally encrypting an already encrypted value.
    if secret.startswith(ENCRYPTED_PREFIX):
        return secret

    encrypted = _get_fernet().encrypt(
        secret.encode("utf-8")
    ).decode("utf-8")

    return ENCRYPTED_PREFIX + encrypted


def decrypt_webhook_secret(secret: str | None) -> str | None:
    """Decrypt a stored webhook secret for delivery signing."""

    if secret is None or not secret:
        return secret

    # Temporary compatibility for existing plaintext records.
    # The migration step will encrypt these records.
    if not secret.startswith(ENCRYPTED_PREFIX):
        return secret

    encrypted_value = secret[len(ENCRYPTED_PREFIX):]

    try:
        return _get_fernet().decrypt(
            encrypted_value.encode("utf-8")
        ).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise RuntimeError(
            "Unable to decrypt webhook secret. "
            "Check WEBHOOK_ENCRYPTION_KEY."
        ) from exc
