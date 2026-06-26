---
name: pytest
description: Run pytest with best practices
---

When running Python tests:
1. Use `python -m pytest` instead of `pytest` for correct sys.path
2. Use `-x` flag to stop on first failure for quick iteration
3. Use `-q` or `--tb=short` for concise output
4. Use `--no-header` to reduce noise
5. For coverage: `python -m pytest --cov=src --cov-report=term-missing`
6. Check `pyproject.toml` for `[tool.pytest.ini_options]` first
