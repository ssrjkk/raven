collect_ignore = []

# pact-python >= 2 removed the Consumer/Provider/Like/Term API that test_pacts.py is
# written against, so the module can be installed and still unusable — check the names.
try:
    import pact

    if not all(hasattr(pact, name) for name in ("Consumer", "Provider", "Like", "Term")):
        collect_ignore.append("test_pacts.py")
except ImportError:
    collect_ignore.append("test_pacts.py")
