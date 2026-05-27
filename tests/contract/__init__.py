from pathlib import Path

try:
    import pact  # noqa: F401
except ImportError:
    import pytest
    collect_ignore = [
        str(p) for p in Path(__file__).parent.rglob("test_pacts.py")
    ]
