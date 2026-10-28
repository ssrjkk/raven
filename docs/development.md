# Development

_by [@ssrjkk](https://github.com/ssrjkk)_

## Setup

```bash
git clone https://github.com/ssrjkk/raven
cd raven
pip install -e ".[dev]"
pre-commit install
```

## Project Structure

```
raven/
├── channels/          # 15 messaging channel adapters
├── cli/               # Click-based CLI (35 command groups)
├── coding/            # Coding assistant, git integration
├── core/              # Core engine
│   ├── gateway/       # Message orchestrator
│   ├── agents/        # Agent system, orchestrators, profiles
│   ├── security/      # Policy engine, sandbox, SSRF, PII redaction
│   ├── task_engine/   # Task planning & execution
│   ├── monitor/       # HTTP, price, RSS, file, process monitors
│   ├── rag/           # Embeddings, BM25, JSON vector store
│   ├── llm/           # LLM providers, failover, circuit breaker
│   ├── config.py      # Settings (env cascade)
│   └── asyncdb.py     # SQLite/PostgreSQL abstraction
├── gateway/           # Gateway glue, channel guardian
├── plugins/           # 10 built-in plugin packages
├── routines/          # Scheduled routines
├── tools/             # 66 assistant tool registry
├── tui/               # Textual TUI
├── voice/             # TTS/STT module
└── workspace/         # Workspace manager, plugin loader

ravencode/             # Autonomous coding agent (runtime, agents, cli)
aios/                  # Thin FastAPI AI-gateway bridge
web/                   # React 19 + Vite dashboard
tests/                 # Test suite
docs/                  # Documentation
deploy/                # Docker, systemd, observability, traefik
```

## Development Loop

```bash
# Quick validation gate (ruff + mypy + imports, no tests)
python scripts/check_all.py --quick

# Full gate (lint + types + imports + all tests + frontend build)
python scripts/check_all.py

# Lint
ruff check .

# Test
pytest tests/ -q --tb=short

# Run gateway
raven start

# Run TUI
raven tui
```

## Testing

```bash
# Run all tests
pytest tests/ -q --tb=short

# Run with coverage
pytest tests/ --cov=raven --cov-report=term-missing

# Run specific test file
pytest tests/core/test_sse.py -v
```

### Design contracts

`tests/test_design_contracts.py`, `tests/test_egress_map.py` and `web/src/design/accent.test.ts`
fail the build on UI regressions, so a design change has to satisfy them rather than look fine on the
author's monitor:

- every `var(--dt-*)` a component asks for must be published by all three themes; the palettes must
  declare the same token set, and each token file must validate against `tokens.schema.json`
- `web/src/styles/themes.css` is generated from the token files (`python scripts/gen_theme_css.py`)
  and declares every theme's tokens before React mounts; the gate regenerates it and fails on any drift, so a
  component never needs a literal fallback — and no component may carry one
- no colour literal outside `web/src/design`: a hex or `rgba()` in a component is a value no theme
  owns, invisible to every contrast rule below. Tailwind palette classes (`text-red-400`,
  `bg-green-900/30`) are forbidden for the same reason — they survive neither a theme switch nor the
  accent picker
- a hover border or focus ring has to be seen to be believed: every `:hover`/`:focus*` rule that sets
  `border-color` or a `0 0 0 Npx` ring is measured at 3:1 against each theme's `surface.card`. That is
  what moved the card hover states off `accent-muted` (a 0.15-alpha wash: 1.13:1, the state changed and
  nobody could see it) and re-clamped dark's `border.focus` to `#8446ee`
- text pairs clear WCAG 2.1 AA (4.5:1 normal, 3:1 for large text and UI parts) in dark, light and
  midnight, computed from the token hexes themselves. That includes `text.on-*` against the fill it
  labels, the fifteen slots of the named categorical scale (`colors.category.*` — blue…grey, shared
  by the knowledge-graph canvas and the plugin tag badges) against the panel they are drawn on, and
  that at least one of the theme's two inverse colours carries an AA label on every one of those
  slots; plus canvas text, whose colours `paint.ts` reads from the theme once a frame because a canvas
  cannot resolve `var()`
- chart series come from `colors.chart.series-*` — no hard-coded hex inside recharts props — are at
  least 3:1 against their own theme's background, and spread over the hue wheel; every
  `<ResponsiveContainer>` sits inside `ChartCard`, which carries the `role="img"` + `aria-label` a
  screen reader needs because recharts paints semantics-free SVG
- any accent the user can pick (`ACCENT_PRESETS`, the accent picker) is clamped by
  `generateAccentPalette` so white button labels stay AA in every state; the matrix is 16 presets ×
  3 themes in vitest
- shipped web surfaces — the SPA, the extension popup, the no-Node fallback page — reference no
  off-origin `src`/`href`, self-host their fonts with a Cyrillic subset, keep a visible focus ring,
  and stop animation under `prefers-reduced-motion`
- the two surfaces that never load the SPA bundle — the gateway's no-Node webchat page and the
  extension popup — embed a generated token region (`python scripts/gen_theme_css.py --print-surface`,
  delimited by `design-tokens:start`/`end` sentinels). A gate compares both regions byte for byte with
  the generator, requires every `var(--dt-*)` they reference to be declared inside the region, forbids
  any other colour literal in those files, forbids an alias no rule uses, and computes their contrast
  pairs from `tokens.json` rather than from hexes copied into the test — including pairs that only
  exist because the page renders markdown in *user* rows too
- the storefront (`site/styles.css`) is gated too: any rule that declares a label and a background is
  measured at AA against each dark panel its wash could land on (worst case kept), and no colour literal
  may appear outside its `:root` scale
- no shipped stylesheet pins itself wider than a phone, and every `<iframe>` is sandboxed without the
  `allow-scripts` + `allow-same-origin` pair that hands the embedder its own origin back

```bash
pytest tests/test_design_contracts.py tests/test_egress_map.py -q --no-cov
cd web && npx vitest run src/design
```

Measured in real Chrome rather than asserted (harness outside the repo): the built stylesheet alone,
with no scripts, paints every theme's page, card and accent values; the inline injection
`ThemeContext` writes afterwards still wins, so a stored accent is not frozen by the static sheet.

## Code Style

- Follow existing patterns in the codebase
- No unnecessary comments
- Type hints required for all function signatures
- Async-first for I/O operations
- Use loguru for logging

## Web Dashboard Assets

The gateway serves the built React SPA from `web/dist`. It is auto-discovered (repo checkout,
installed wheel, PyInstaller bundle, or `RAVEN_WEB_DIST` override):

```bash
cd web && npm ci && npm run build   # produces web/dist
```

Wheel/sdist builds pick up the SPA when CI stages it inside the package (`raven/web/dist`) —
see `.github/workflows/pypi.yml`; the Docker image builds it in a dedicated stage and points
`RAVEN_WEB_DIST` at it.

## Icons

```bash
python scripts/make_icon.py                 # scripts/raven.ico (skipped if present)
python scripts/make_extension_icons.py      # extension/icons/*.png + extension/vscode/icon.png
```

## Building

```bash
pip install build
python -m build
```
