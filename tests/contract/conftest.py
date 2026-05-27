collect_ignore = []

try:
    import pact  # noqa: F401
except ImportError:
    collect_ignore.append("test_pacts.py")
