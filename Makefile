.PHONY: setup up down logs shell clean

setup:
	pip install -e ".[dev]"
	mkdir -p workspace data/secrets
	@if not exist .env ( copy .env.example .env 2>nul || echo. > .env )
	echo Setup complete. Edit .env with your API keys.

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

shell:
	python -m raven shell

clean:
	rmdir /s /q __pycache__ 2>nul
	rmdir /s /q .pytest_cache 2>nul
	rmdir /s /q .mypy_cache 2>nul
	rmdir /s /q build 2>nul
	rmdir /s /q dist 2>nul
	for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
