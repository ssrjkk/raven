from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from raven.core.db import Database

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC as PBKDF2

    HAS_CRYPTO = True
except ImportError:  # pragma: no cover
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
        self._db: Database | None = None
        self._db_path: str | None = None

    def bind_db(self, db: Database) -> None:
        self._db = db
        if self._loaded:
            return
        self._loaded = True

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
            raise RuntimeError(
                "Cryptography package not installed. "
                "Run: pip install cryptography"
            )
        key = self._get_or_create_key()
        if not key:
            raise RuntimeError(
                "RAVEN_MASTER_KEY not set. "
                "Set it in .env or config"
            )
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
            return f.decrypt(ciphertext[len(_MARKER):].encode()).decode()
        except Exception as e:
            logger.error("Secrets decryption failed: {}", e)
            return ciphertext

    def load(self):
        if self._loaded:
            return
        self._loaded = True

        if self._db is not None:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._load_from_db())
                return
            except RuntimeError:
                pass

        self._load_from_file()

    def _load_from_file(self):
        if not self._enc_path.exists():
            return
        try:
            import json
            raw = self._enc_path.read_text()
            encrypted = json.loads(raw)
            self._cache = {k: self.decrypt(v) for k, v in encrypted.items()}
            logger.info("Loaded {} secrets from file", len(self._cache))
        except Exception as e:
            logger.error("Failed to load secrets from file: {}", e)

    async def _load_from_db(self):
        if not self._db:
            return
        try:
            keys = await self._db.list_secrets()
            for key in keys:
                enc = await self._db.get_secret(key)
                if enc:
                    self._cache[key] = self.decrypt(enc)
            logger.info("Loaded {} secrets from database", len(self._cache))
        except Exception as e:
            logger.error("Failed to load secrets from database: {}", e)

    def save(self):
        if self._db is not None:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._save_to_db())
                return
            except RuntimeError:
                pass
        self._save_to_file()

    def _save_to_file(self):
        import json
        encrypted = {k: self.encrypt(v) for k, v in self._cache.items()}
        self._enc_path.write_text(json.dumps(encrypted, indent=2))
        self._enc_path.chmod(0o600)

    async def _save_to_db(self):
        if not self._db:
            self._save_to_file()
            return
        try:
            for key, value in self._cache.items():
                enc = self.encrypt(value)
                await self._db.save_secret(key, enc)
            logger.debug("Saved {} secrets to database", len(self._cache))
        except Exception as e:
            logger.error("Failed to save secrets to database: {}", e)

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
