from __future__ import annotations

import hashlib
import os
import secrets as _secrets

_PBKDF2_ITERATIONS = 600_000
_LEGACY_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return salt.hex() + ":" + key.hex()


def check_password_strength(password: str) -> None:
    """The one password policy the product has, in the one place it is written.

    It used to live inside `AuthRegisterRequest`, so only the registration route enforced it. Any
    other path that writes `password_hash` — the admin bootstrap CLI above all — would otherwise mint
    an account the whole system trusts on a credential the documented policy refuses.
    """
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not any(c.isupper() for c in password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not any(c.islower() for c in password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password must contain at least one digit")
    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        raise ValueError("Password must contain at least one special character")


def verify_password(password: str, hashed: str) -> bool:
    try:
        salt_hex, key_hex = hashed.split(":")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(key_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
        if _secrets.compare_digest(actual, expected):
            return True
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _LEGACY_ITERATIONS)
        return _secrets.compare_digest(actual, expected)
    except (ValueError, AttributeError):
        return False


def verify_and_rehash(password: str, hashed: str) -> tuple[str | None, bool]:
    try:
        salt_hex, key_hex = hashed.split(":")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(key_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
        if _secrets.compare_digest(actual, expected):
            return None, True
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _LEGACY_ITERATIONS)
        if _secrets.compare_digest(actual, expected):
            return hash_password(password), True
        return None, False
    except (ValueError, AttributeError):
        return None, False


# A fixed PBKDF2 hash used to equalize login timing when a username does not
# exist (or has no password), preventing user-enumeration via response time.
_DUMMY_PASSWORD_HASH = hash_password("raven-timing-dummy")


def dummy_verify(password: str) -> None:
    """Run a PBKDF2 verification against a fixed dummy hash (timing equalizer)."""
    verify_password(password, _DUMMY_PASSWORD_HASH)
