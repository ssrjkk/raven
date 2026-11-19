"""The path names that mean a credential, so every confine in the project refuses them the same way.

Three resolvers guard a filesystem path today (`raven/core/workspace.py`, `ravencode/runtime/workspace.py`,
`raven/core/security/path_guard.py`) and a fourth decides it in the tool policy, so the rule belongs in
one module the four of them import rather than in whichever one a given tool happens to call.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Sequence
from pathlib import Path

# What the agent reads goes into a model prompt and out through whichever channel asked for it, so a
# credential is refused by name before the read rather than redacted after it. A secret whose name
# says nothing is a secret no tool had a business reason to open.
CREDENTIAL_DIRS: frozenset[str] = frozenset({".ssh", ".aws", ".gnupg", ".azure"})

CREDENTIAL_NAMES: frozenset[str] = frozenset(
    {".git-credentials", ".npmrc", ".pypirc", "netrc", "_netrc", "web_secret_key"}
)

CREDENTIAL_SUFFIXES: tuple[str, ...] = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx")

CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\.env(\..+)?$"),
    re.compile(r"^id_(rsa|dsa|ecdsa|ed25519)$"),
)

# A template ships beside the real file and holds placeholders, so `cp .env.example .env` still works.
HARMLESS_SUFFIXES: tuple[str, ...] = (".example", ".sample", ".template", ".tpl", ".dist", ".md", ".pub")


def credential_in_args(tokens: Sequence[str], root: Path) -> str | None:
    """Why a command line names a credential file, or None when it does not.

    A shell tool reaches a file just as plainly as `files.read` does: `cat .env` is the same read.
    Whole arguments are judged, so prose that happens to end in a dot survives. This raises the bar,
    it does not seal the surface: an interpreter in the allowlist reads whatever it is told to, which
    is why the child also starts in the workspace without the gateway's secret-bearing environment.
    """
    for token in tokens:
        candidate = Path(token).expanduser()
        try:
            resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
        except (RuntimeError, OSError):
            continue
        reason = credential_reason(resolved, root)
        if reason is not None:
            return f"'{token}' {reason}"
    return None


def credential_reason(path: Path, root: Path | None = None) -> str | None:
    """Why this path names a credential, or None when it does not.

    Only the segments below ``root`` are judged: a checkout that happens to live under a directory
    named in the list is not itself a credential.
    """
    parts = path.parts
    if root is not None:
        with contextlib.suppress(ValueError):
            parts = path.relative_to(root).parts
    for segment in parts:
        name = segment.lower()
        if name.endswith(HARMLESS_SUFFIXES):
            continue
        if name in CREDENTIAL_DIRS:
            return f"is inside the credential directory '{segment}'"
        if name in CREDENTIAL_NAMES:
            return f"is a credential store ('{segment}')"
        if name.endswith(CREDENTIAL_SUFFIXES):
            return f"is a credential key file ('{segment}')"
        if any(pattern.match(name) for pattern in CREDENTIAL_PATTERNS):
            return f"is a credential file ('{segment}')"
    return None
