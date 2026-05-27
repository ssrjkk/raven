.PHONY: all tidy build clean

GO_SERVICES = gateway auth monitor-engine

all: tidy build

tidy:
	@for svc in $(GO_SERVICES); do \
		echo "=== $$svc: go mod tidy ==="; \
		cd services/$$svc && go mod tidy && cd ../..; \
	done

build:
	@for svc in $(GO_SERVICES); do \
		echo "=== $$svc: go build ==="; \
		cd services/$$svc && go build -o bin/$$svc . && cd ../..; \
	done

clean:
	@for svc in $(GO_SERVICES); do \
		rm -f services/$$svc/bin/$$svc; \
	done
