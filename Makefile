.PHONY: lint test test-web build build-web dev dev-web clean

# Python
lint:
	ruff check .
	mypy raven/ --strict --ignore-missing-imports || true

test:
	pytest tests/ -v --cov=raven --cov-report=term

# Web
test-web:
	cd web && npm run lint

build-web:
	cd web && npm install && npm run build

dev-web:
	cd web && npm run dev

# Docker
build:
	docker compose build

dev:
	raven start

# Cleanup
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	rm -rf web/dist web/node_modules

# Go
go-lint:
	@for svc in gateway auth monitor-engine; do \
		cd services/$$svc && go vet ./... && cd ../..; \
	done
