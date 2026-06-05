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
git clone https://github.com/ssrjkk/raven
cd raven
pip install -e ".[dev]"
```

#### Development Loop

```bash
# Lint
ruff check .

# Type check
mypy raven/ --strict --ignore-missing-imports

# Test
pytest tests/ -q --tb=short

# Test with coverage
pytest tests/ --cov=raven --cov-report=term-missing

# Build web
cd web && npm install && npm run build
```

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
7. Open a Pull Request against `main`
8. Respond to review feedback

### 4. Project Structure

```
raven/
├── raven/             # Core Python package (agent, auth, gateway, LLM, RAG, etc.)
├── services/          # Microservices (Go: gateway/auth/monitor-engine; Python: agent-core/rag/task/code)
├── channels/          # 12 messaging channels (Telegram, Discord, Slack, etc.)
├── web/               # React 19 + Vite + Tailwind dashboard
├── aios/              # AI-OS-MVP bridge
├── daemon/            # Rust system daemon
├── ravencode/         # Python API for AI agents
├── packages/          # TypeScript shared packages
├── plugins/           # 10 plugin tools
├── deploy/            # Docker, K8s, observability configs
├── tests/             # Test suite (pytest)
├── docs/              # MkDocs documentation
└── scripts/           # Setup and build scripts
```

## Development Channels

- **stable**: Released versions from PyPI
- **dev**: `main` branch — may be unstable

## Getting Help

- Open a [Discussion](https://github.com/ssrjkk/raven/discussions)
- Join our community chat (if available)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
