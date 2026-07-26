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
