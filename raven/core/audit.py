from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from loguru import logger

AUDIT_SIGNING_KEY_ENV = "RAVEN_AUDIT_SIGNING_KEY"
AUDIT_KEY_FILE = "data/audit_signing_key.bin"


class AuditEventType(StrEnum):
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_SENT = "message.sent"
    USER_AUTH = "user.auth"
    USER_PAIR = "user.pair"
    USER_BLOCK = "user.block"
    COMMAND = "command"
    CONFIG_CHANGE = "config.change"
    CHANNEL_START = "channel.start"
    CHANNEL_STOP = "channel.stop"
    CHANNEL_ERROR = "channel.error"
    LLM_CALL = "llm.call"
    LLM_ERROR = "llm.error"
    PLUGIN_CALL = "plugin.call"
    SANDBOX_EXEC = "sandbox.exec"
    ADMIN_ACTION = "admin.action"
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    TOOL_EXEC = "tool.exec"
    POLICY_EVAL = "policy.eval"
    PII_REDACTED = "pii.redacted"
    ERROR = "error"


@dataclass
class AuditEntry:
    timestamp: float
    event_id: str
    event: str
    actor: str
    target: str = ""
    detail: Any = None
    channel: str = ""
    prev_hash: str = ""
    hash: str = ""
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "timestamp": self.timestamp,
            "event_id": self.event_id,
            "event": self.event,
            "actor": self.actor,
            "target": self.target,
            "detail": self.detail,
            "channel": self.channel,
        }
        if self.hash:
            d["prev_hash"] = self.prev_hash
            d["hash"] = self.hash
        if self.signature:
            d["signature"] = self.signature
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AuditEntry:
        return cls(
            timestamp=d.get("timestamp", 0.0),
            event_id=d.get("event_id", ""),
            event=d.get("event", ""),
            actor=d.get("actor", ""),
            target=d.get("target", ""),
            detail=d.get("detail"),
            channel=d.get("channel", ""),
            prev_hash=d.get("prev_hash", ""),
            hash=d.get("hash", ""),
            signature=d.get("signature", ""),
        )

    @property
    def timestamp_dt(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp)

    def __repr__(self) -> str:
        return f"AuditEntry({self.event}, {self.actor}, {self.target})"


def _restrict_key_file(path: Path):
    try:
        import subprocess

        if os.name == "nt":
            username = os.environ.get("USERNAME") or os.environ.get("USER", "")
            if username:
                subprocess.run(
                    ["icacls", str(path), "/inheritance:r", "/grant", f"{username}:F"],
                    capture_output=True,
                )
    except Exception as exc:
        logger.warning("Failed to restrict key file permissions: {}", exc)


def _load_or_generate_signing_key() -> tuple[bytes, bool]:
    key_file = Path(AUDIT_KEY_FILE)
    if key_file.exists():
        return key_file.read_bytes(), False

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        private_key = Ed25519PrivateKey.generate()
        raw = private_key.private_bytes_raw()
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(raw)
        _restrict_key_file(key_file)
        logger.info("Generated new Ed25519 audit signing key at {}", key_file)
        return raw, True
    except Exception as e:
        logger.warning("Cannot generate Ed25519 key, signing disabled: {}", e)
        return b"", False


class AuditLogger:
    def __init__(
        self,
        log_path: str = "data/audit.log",
        signing_key: bytes | None = None,
    ):
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file: io.TextIOWrapper | None = None
        self._closed = False
        self._prev_hash = ""
        self._lock = asyncio.Lock()

        env_key = os.environ.get(AUDIT_SIGNING_KEY_ENV)
        if env_key:
            try:
                signing_key = bytes.fromhex(env_key)
            except Exception:
                logger.warning("Invalid RAVEN_AUDIT_SIGNING_KEY hex, falling back")
                signing_key = None

        if signing_key is None:
            signing_key, _generated = _load_or_generate_signing_key()

        self._signing_key = signing_key or None
        self._use_signing = self._signing_key is not None
        self._public_key: Any = None

    def start(self):
        self._file = self._path.open("a", encoding="utf-8")
        if self._use_signing:
            self._prev_hash = self._last_entry_hash()

        if self._path.exists() and self._path.stat().st_size > 0:
            errors = self.verify_chain()
            if errors and not errors[0].get("valid"):
                logger.error("Audit log chain integrity check FAILED: {} errors", len(errors))
                for err in errors[:5]:
                    logger.error("  [line {}] {}: {}", err.get("line"), err.get("error"), err.get("event_id"))

    async def stop(self):
        async with self._lock:
            self._closed = True
            self._close_file()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def is_open(self) -> bool:
        return self._file is not None and not self._closed

    @property
    def is_signed(self) -> bool:
        return self._use_signing

    @property
    def signing_key(self) -> bytes | None:
        return self._signing_key

    def _close_file(self):
        if self._file:
            self._file.close()
            self._file = None

    def _last_entry_hash(self) -> str:
        if not self._path.exists() or self._path.stat().st_size == 0:
            return "0" * 64
        with self._path.open("rb") as f:
            last_line = b""
            for line in f:
                last_line = line.strip()
        if last_line:
            try:
                entry = json.loads(last_line)
                return entry.get("hash", "0" * 64)  # type: ignore[no-any-return]
            except (json.JSONDecodeError, KeyError):
                pass
        return "0" * 64

    def _compute_hash(self, entry_dict: dict[str, Any]) -> str:
        payload = json.dumps(entry_dict, sort_keys=True, default=str).encode()
        return hashlib.sha256(payload).hexdigest()

    def _compute_signature(self, payload: bytes) -> str:
        if not self._use_signing:
            return ""
        try:
            from cryptography.hazmat.primitives.asymmetric import ed25519

            private_key = ed25519.Ed25519PrivateKey.from_private_bytes(self._signing_key or b"")
            sig = private_key.sign(payload)
            return sig.hex()
        except Exception as e:
            logger.warning("Audit signing failed: {}", e)
            return ""

    async def log(
        self,
        event_type: AuditEventType | str,
        actor: str,
        target: str = "",
        detail: Any = None,
        channel: str = "",
    ):
        async with self._lock:
            if self._closed:
                logger.warning("Audit log is closed, dropping event")
                return

            entry = AuditEntry(
                timestamp=time.time(),
                event_id=uuid.uuid4().hex[:16],
                event=event_type.value if isinstance(event_type, AuditEventType) else event_type,
                actor=actor,
                target=target,
                detail=detail,
                channel=channel,
            )

            if self._use_signing:
                entry.prev_hash = self._prev_hash
                entry.hash = self._compute_hash(
                    {k: v for k, v in entry.to_dict().items() if k not in ("prev_hash", "hash", "signature")}
                )
                entry.signature = self._compute_signature(json.dumps(entry.to_dict(), sort_keys=True, default=str).encode())
                self._prev_hash = entry.hash

            line = json.dumps(entry.to_dict(), default=str)
            if not self._file:
                logger.warning("Audit log not started, dropping event")
                return
            try:
                self._file.write(line + "\n")
                self._file.flush()
                os.fsync(self._file.fileno())
            except OSError as e:
                logger.error("Audit log write failed: {}", e)

        logger.debug("[audit] {} | {} | {}", entry.event, actor, target)

    async def sensitive(self, event_type: str, actor: str, target: str, outcome: bool):
        await self.log(event_type, actor, target, {"sensitive": True, "outcome": outcome})

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with self._path.open() as f:
            lines = f.readlines()[-limit:]
        result = []
        for line in lines:
            try:
                entry = json.loads(line)
                result.append(entry)
            except json.JSONDecodeError:
                pass
        return result

    def query(
        self,
        event_type: str | None = None,
        actor: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        if not self._path.exists():
            return []
        results: list[AuditEntry] = []
        with self._path.open() as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    ae = AuditEntry.from_dict(entry)
                    if event_type and ae.event != event_type:
                        continue
                    if actor and ae.actor != actor:
                        continue
                    if since is not None and ae.timestamp < since:
                        continue
                    if until is not None and ae.timestamp > until:
                        continue
                    results.append(ae)
                    if len(results) >= limit:
                        break
                except json.JSONDecodeError:
                    pass
        return results

    def stats(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"total": 0, "by_event": {}, "by_actor": {}}
        total = 0
        by_event: dict[str, int] = {}
        by_actor: dict[str, int] = {}
        first_ts: float | None = None
        last_ts: float | None = None
        parse_errors = 0
        with self._path.open() as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    total += 1
                    ev = entry.get("event", "unknown")
                    by_event[ev] = by_event.get(ev, 0) + 1
                    act = entry.get("actor", "unknown")
                    by_actor[act] = by_actor.get(act, 0) + 1
                    ts = entry.get("timestamp", 0)
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts
                except json.JSONDecodeError:
                    parse_errors += 1
        return {
            "total": total,
            "by_event": by_event,
            "by_actor": by_actor,
            "first_event": datetime.fromtimestamp(first_ts).isoformat() if first_ts else None,
            "last_event": datetime.fromtimestamp(last_ts).isoformat() if last_ts else None,
            "parse_errors": parse_errors,
            "path": str(self._path),
            "size_bytes": self._path.stat().st_size if self._path.exists() else 0,
            "signed": self._use_signing,
        }

    def verify_chain(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return [{"valid": True, "entries": 0}]
        errors: list[dict[str, Any]] = []
        prev_hash = "0" * 64
        entry_count = 0
        i = 0
        with self._path.open() as f:
            for i, line in enumerate(f, 1):
                try:
                    entry = json.loads(line)
                    entry_count += 1
                    expected_hash = entry.get("hash", "")
                    if not expected_hash:
                        continue
                    content = {k: v for k, v in entry.items() if k not in ("hash", "signature", "prev_hash")}
                    actual_hash = hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()
                    if actual_hash != expected_hash:
                        errors.append(
                            {
                                "line": i,
                                "error": "hash_mismatch",
                                "event_id": entry.get("event_id"),
                                "expected": expected_hash,
                                "actual": actual_hash,
                            }
                        )
                    pe = entry.get("prev_hash", "0" * 64)
                    if pe != prev_hash:
                        errors.append(
                            {
                                "line": i,
                                "error": "chain_break",
                                "event_id": entry.get("event_id"),
                                "expected_prev": prev_hash,
                                "actual_prev": pe,
                            }
                        )
                    prev_hash = entry.get("hash", "0" * 64)
                except json.JSONDecodeError:
                    errors.append({"line": i, "error": "parse_error"})
        return errors or [{"valid": True, "entries": entry_count, "lines_scanned": i}]

    def _get_public_key(self) -> Any:
        if self._public_key is not None:
            return self._public_key
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

            private_key = Ed25519PrivateKey.from_private_bytes(self._signing_key or b"")
            self._public_key = private_key.public_key()
        except Exception as exc:
            logger.warning("Cannot derive Ed25519 public key: {}", exc)
            return None
        return self._public_key

    def verify_signatures(self) -> list[dict[str, Any]]:
        if not self._use_signing or not self._path.exists():
            return [{"valid": True, "note": "signing not enabled"}]
        public_key = self._get_public_key()
        if public_key is None:
            return [{"valid": False, "note": "cannot derive public key"}]
        errors: list[dict[str, Any]] = []
        with self._path.open() as f:
            for i, line in enumerate(f, 1):
                try:
                    entry = json.loads(line)
                    sig_hex = entry.get("signature", "")
                    if not sig_hex:
                        continue
                    content = {k: v for k, v in entry.items() if k != "signature"}
                    payload = json.dumps(content, sort_keys=True, default=str).encode()
                    try:
                        public_key.verify(bytes.fromhex(sig_hex), payload)
                    except Exception:
                        errors.append(
                            {
                                "line": i,
                                "error": "signature_mismatch",
                                "event_id": entry.get("event_id"),
                            }
                        )
                except json.JSONDecodeError:
                    pass
        return errors or [{"valid": True, "signatures_verified": True}]


audit_logger = AuditLogger()
