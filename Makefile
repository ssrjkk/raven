# Raven AI — developer shortcuts (by ssrjkk)
.PHONY: setup up down logs shell check check-quick test web-build web-test icons clean

setup:
	pip install -e ".[dev]"
	python -c "from pathlib import Path; [Path(p).mkdir(parents=True, exist_ok=True) for p in ('workspace', 'data')]"
	python -c "from pathlib import Path; import shutil; Path('.env').exists() or shutil.copy('.env.example', '.env')"
	@echo "Setup complete — edit .env with your API keys (or run: raven onboard)"

up:
	docker compose --profile minimal up -d

down:
	docker compose down

logs:
	docker compose logs -f

shell:
	python -m raven shell

check:
	python scripts/check_all.py

check-quick:
	python scripts/check_all.py --quick

test:
	python -m pytest -q

web-build:
	cd web && npm ci && npm run build

web-test:
	cd web && npm test -- --run

icons:
	python scripts/make_icon.py
	python scripts/make_extension_icons.py

clean:
	python -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ('.pytest_cache', '.mypy_cache', '.ruff_cache', 'build', 'dist')]"
	python -c "import shutil, pathlib; [shutil.rmtree(d, ignore_errors=True) for d in pathlib.Path('.').rglob('__pycache__')]"

