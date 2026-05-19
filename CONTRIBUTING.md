# Contributing to Raven AI

Thank you for your interest in contributing to Raven AI! We welcome contributions from everyone.

## Code of Conduct

By participating, you agree to maintain a respectful and inclusive environment for all contributors.

## How to Contribute

### 1. Reporting Bugs

- Check existing issues to avoid duplicates
- Use the bug report template
- Include: Python version, OS, steps to reproduce, expected vs actual behavior
- Include relevant logs and configuration (redact secrets)

### 2. Suggesting Features

- Check existing issues and discussions
- Describe the problem you're solving, not just your proposed solution
- Explain how it benefits the project

### 3. Pull Requests

#### Setup

```bash
git clone https://github.com/yourusername/raven
cd raven
pip install -e ".[dev]"
```

#### Development Loop

```bash
# Lint
ruff check .

# Type check
ruff check . 

# Test
pytest tests/ -q --tb=short

# Test with coverage
pytest tests/ --cov=raven --cov-report=term-missing
```

#### Pre-commit

We use pre-commit hooks to ensure code quality:

```bash
pip install pre-commit
pre-commit install
```

Hooks will run automatically on `git commit`. They check:
- Ruff linting
- Trailing whitespace
- File endings
- YAML/JSON validity

#### Guidelines

- **Code style**: Follow existing patterns; no comments unless necessary
- **Tests**: Add tests for new features; ensure all tests pass
- **Documentation**: Update docstrings and relevant docs
- **Single responsibility**: One PR = one feature or bug fix
- **Commit messages**: Concise, descriptive, present tense

#### PR Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/amazing-feature`)
3. Make your changes
4. Run lint and tests
5. Commit with a clear message
6. Push to your fork
7. Open a Pull Request against `master`
8. Respond to review feedback

### 4. Project Structure

```
raven/
├── channels/          # Messaging channel implementations
├── cli/               # CLI commands (Click-based)
├── core/              # Core logic (LLM, config, security, etc.)
├── plugins/           # Plugin tools (files, code, browser, etc.)
├── tools/             # Built-in tool registry
├── tui/               # Textual TUI dashboard
└── routines/          # Automated routine engine

tests/                 # Test suite (pytest)
web/                   # React web frontend
docs/                  # Documentation (MkDocs)
deploy/                # Deployment configs
scripts/               # Setup scripts
```

## Development Channels

- **stable**: Released versions from PyPI
- **dev**: `master` branch — may be unstable

## Getting Help

- Open a [Discussion](https://github.com/yourusername/raven/discussions)
- Join our community chat (if available)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
