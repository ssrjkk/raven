"""Credential masking for data that leaves the machine.

   Memory tiers and session files hold whatever the assistant was told, which includes provider
   keys, so an export written verbatim becomes a leak the moment the file is shared. This is the
   one place that decides what a credential looks like: `raven backup export --sanitize` and
   `ravencode session export --sanitize` both call it, so the two cannot drift apart."""

from __future__ import annotations

import re
from typing import Any

MASK = "***"

# The separators keep "monkey", "tokenizer" and "keyboard" out; the bare "key" at the end is what
# catches a dict entry named "key" holding someone's token.
NAME_RE = re.compile(
    r"(?:^|[^a-zA-Z])(?:api[_-]?keys?|access[_-]?keys?|secrets?|tokens?|passwords?|passwd|"
    r"credentials?|authorization|private[_-]?keys?|keys?)(?:$|[^a-zA-Z])",
    re.IGNORECASE,
)

# Deliberately specific: a broad "32+ alphanumerics" rule would mask session ids and hashes too,
# which makes an export useless without making it any safer.
VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:sk-ant-[A-Za-z0-9-]{6,}|sk-[A-Za-z0-9_-]{6,}|gh[pousr]_[A-Za-z0-9]{16,}|"
    r"github_pat_[A-Za-z0-9_]{16,}|AIza[0-9A-Za-z_-]{20,}|xox[baprs]-[A-Za-z0-9-]{6,}|"
    r"AKIA[0-9A-Z]{16}|npm_[A-Za-z0-9]{20,})"
    r"|Bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r"|\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s:@]+@[^\s]+",
    re.IGNORECASE,
)


def name_is_credential(key: Any) -> bool:
    return bool(NAME_RE.search(str(key)))


def mask_string(text: str) -> str:
    return VALUE_RE.sub(MASK, text)


def mask_deep(value: Any) -> Any:
    if isinstance(value, str):
        return mask_string(value)
    if isinstance(value, dict):
        return {k: MASK if name_is_credential(k) else mask_deep(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_deep(item) for item in value]
    return value


def mask_entry(key: Any, value: Any) -> Any:
    """A memory entry names its own credential, so the name decides before the shapes do."""
    return MASK if name_is_credential(key) else mask_deep(value)
