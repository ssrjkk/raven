from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from loguru import logger

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC as PBKDF2

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

_KEY_FILE = "data/.secrets_key"
_ENCRYPTED_FILE = "data/secrets.enc"
_MARKER = "enc:"


def _derive_key(master_key: str, salt: bytes) -> bytes:
    if not HAS_CRYPTO:
        return b""
    kdf = PBKDF2(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
    return base64.urlsafe_b64encode(kdf.derive(master_key.encode()))


class SecretsManager:
    def __init__(self, data_dir: str = "data"):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._key_path = self._data_dir / ".secrets_key"
        self._enc_path = self._data_dir / "secrets.enc"
        self._cache: dict[str, str] = {}
        self._loaded = False

    def _get_or_create_key(self) -> bytes:
        master = os.environ.get("RAVEN_MASTER_KEY", "")
        if not master:
            return b""
        salt = self._key_path.read_bytes() if self._key_path.exists() else os.urandom(16)
        if not self._key_path.exists():
            self._key_path.write_bytes(salt)
            self._key_path.chmod(0o600)
        return _derive_key(master, salt)

    def encrypt(self, plaintext: str) -> str:
        if not HAS_CRYPTO:
            return plaintext
        key = self._get_or_create_key()
        if not key:
            return plaintext
        f = Fernet(key)
        return _MARKER + f.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext.startswith(_MARKER):
            return ciphertext
        key = self._get_or_create_key()
        if not key:
            logger.warning("RAVEN_MASTER_KEY not set, cannot decrypt secrets")
            return ciphertext
        f = Fernet(key)
        try:
            return f.decrypt(ciphertext[len(_MARKER) :].encode()).decode()
        except Exception as e:
            logger.error("Secrets decryption failed: {}", e)
            return ciphertext

    def load(self):
        if self._loaded:
            return
        if self._enc_path.exists():
            try:
                raw = self._enc_path.read_text()
                encrypted = json.loads(raw)
                self._cache = {k: self.decrypt(v) for k, v in encrypted.items()}
            except Exception as e:
                logger.error("Failed to load secrets: {}", e)
        self._loaded = True

    def save(self):
        encrypted = {k: self.encrypt(v) for k, v in self._cache.items()}
        self._enc_path.write_text(json.dumps(encrypted, indent=2))
        self._enc_path.chmod(0o600)

    def get(self, key: str, default: str = "") -> str:
        return self._cache.get(key, default)

    def set(self, key: str, value: str):
        self._cache[key] = value
        self.save()

    def unset(self, key: str):
        self._cache.pop(key, None)
        self.save()

    def list_keys(self) -> list[str]:
        return list(self._cache.keys())


secrets = SecretsManager()
