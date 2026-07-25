collect_ignore = []

try:
    import pact
except ImportError:
    collect_ignore.append("test_pacts.py")
