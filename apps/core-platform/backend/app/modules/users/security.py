"""Users security primitives: password hashing + one-time-code hashing.

Password hashing is bcrypt (cost from ``PASSWORD_BCRYPT_ROUNDS``). One-time
reset codes are stored as a keyed HMAC-SHA256, never plaintext: a 4-digit
code's real defense is the attempt cap + short TTL, but keying the hash means
a leaked DB row cannot be reversed into a code without the server key.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

import bcrypt
import structlog

from app.core.conf import settings

logger = structlog.get_logger("app.users.security")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(
        plain.encode("utf-8"), bcrypt.gensalt(rounds=settings.PASSWORD_BCRYPT_ROUNDS)
    ).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    """Constant-ish bcrypt check. Never raises — a malformed/legacy stored hash
    is treated as a failed login (401), not a 500."""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception as e:  # noqa: BLE001 — invalid salt / unsupported hash format
        logger.warning("password_verify_failed", reason=type(e).__name__)
        return False


def _reset_key() -> bytes:
    # Dedicated key when set; otherwise the app's JWT secret (never a literal).
    return (settings.PASSWORD_RESET_HMAC_KEY or settings.JWT_SECRET_KEY).encode("utf-8")


def hash_one_time_code(code: str) -> str:
    return hmac.new(_reset_key(), code.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_one_time_code(code: str, code_hash: str | None) -> bool:
    if not code or not code_hash:
        return False
    return hmac.compare_digest(hash_one_time_code(code), code_hash)


def generate_numeric_code(length: int) -> str:
    if length <= 0:
        raise ValueError("code length must be positive")
    return "".join(secrets.choice("0123456789") for _ in range(length))
