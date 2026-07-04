from __future__ import annotations

import asyncio
import base64
import json
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
except ImportError:
    HAS_CRYPTO = False

_MARKER = "enc:"
_PBKDF2_ITERATIONS = 600_000


def _derive_key(master_key: str, salt: bytes) -> bytes:
    if not HAS_CRYPTO:
        return b""
    kdf = PBKDF2(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_PBKDF2_ITERATIONS)
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
        self._lock = asyncio.Lock()
        self._fernet_key: bytes | None = None
        self._fernet_salt: bytes | None = None

    async def bind_db(self, db: Database) -> None:
        self._db = db
        await self._load_from_db()

    def _get_or_create_key(self) -> bytes:
        master = os.environ.get("RAVEN_MASTER_KEY", "")
        if not master:
            raise RuntimeError("RAVEN_MASTER_KEY not set. Set it in .env or config.")
        salt = self._key_path.read_bytes() if self._key_path.exists() else os.urandom(16)
        if salt == self._fernet_salt and self._fernet_key:
            return self._fernet_key
        if not self._key_path.exists():
            self._key_path.write_bytes(salt)
        derived = _derive_key(master, salt)
        self._fernet_key = derived
        self._fernet_salt = salt
        return derived

    def encrypt(self, plaintext: str) -> str:
        if not HAS_CRYPTO:
            raise RuntimeError("Cryptography package not installed. Run: pip install cryptography")
        key = self._get_or_create_key()
        f = Fernet(key)
        return _MARKER + f.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext.startswith(_MARKER):
            return ciphertext
        key = self._get_or_create_key()
        f = Fernet(key)
        try:
            return f.decrypt(ciphertext[len(_MARKER):].encode()).decode()
        except Exception as e:
            raise RuntimeError(f"Secrets decryption failed: {e}") from e

    async def load(self):
        async with self._lock:
            if self._loaded:
                return
            self._loaded = True
            if self._db is not None:
                await self._load_from_db()
            else:
                self._load_from_file()

    def _load_from_file(self):
        if not self._enc_path.exists():
            return
        try:
            raw = self._enc_path.read_text()
            encrypted = json.loads(raw)
            for k, v in encrypted.items():
                self._cache[k] = self.decrypt(v)
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
            self._loaded = True
            logger.info("Loaded {} secrets from database", len(self._cache))
        except Exception as e:
            logger.error("Failed to load secrets from database: {}", e)

    async def save(self):
        async with self._lock:
            if self._db is not None:
                await self._save_to_db()
            self._save_to_file()

    def _save_to_file(self):
        encrypted = {k: self.encrypt(v) for k, v in self._cache.items()}
        tmp = self._enc_path.with_suffix(".enc.tmp")
        try:
            tmp.write_text(json.dumps(encrypted, indent=2))
            tmp.replace(self._enc_path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    async def _save_to_db(self):
        if not self._db:
            self._save_to_file()
            return
        try:
            db_keys = set(await self._db.list_secrets())
            cache_keys = set(self._cache.keys())
            for key in db_keys - cache_keys:
                await self._db.delete_secret(key)
            for key, value in self._cache.items():
                enc = self.encrypt(value)
                await self._db.save_secret(key, enc)
            logger.debug("Saved {} secrets to database", len(self._cache))
        except Exception as e:
            logger.error("Failed to save secrets to database: {}", e)

    def get(self, key: str, default: str = "") -> str:
        return self._cache.get(key, default)

    async def set(self, key: str, value: str):
        async with self._lock:
            self._cache[key] = value
        await self.save()

    async def unset(self, key: str):
        async with self._lock:
            self._cache.pop(key, None)
        await self.save()

    def list_keys(self) -> list[str]:
        return list(self._cache.keys())


secrets = SecretsManager()
