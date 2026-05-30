GO_SERVICES = gateway auth monitor-engine
PY_SERVICES = agent-core rag-service task-engine code-service

.PHONY: all build-go build-py test lint clean up proto

all: lint build-go test

build-go:
	@for svc in $(GO_SERVICES); do \
		echo "Building $$svc..."; \
		cd services/$$svc && go build ./... && cd ../..; \
	done

vet-go:
	@for svc in $(GO_SERVICES); do \
		echo "Vetting $$svc..."; \
		cd services/$$svc && go vet ./... && cd ../..; \
	done

build-py:
	@echo "Checking Python syntax..."
	python -c "import ast; import glob; [ast.parse(open(f).read()) for f in glob.glob('services/*/main.py')]"

test:
	python -m pytest tests/ -q --tb=short

lint:
	ruff check --output-format=concise .
	mypy --strict --ignore-missing-imports raven/ services/ || true

proto:
	cd services/proto && buf generate

proto-lint:
	cd services/proto && buf lint

up:
	docker compose -f deploy/docker-compose.yml up -d

down:
	docker compose -f deploy/docker-compose.yml down

k6:
	k6 run --vus 10 --duration 30s tests/load/scenario.js

clean:
	rm -f services/*/bin/*
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

.PHONY: all build-go build-py test lint clean up down proto proto-lint k6 vet-go
