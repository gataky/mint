# The target names, their behavior, and their output are the contract this
# service shares with the Python service. Jumping between the two should feel
# identical. If you add a target here, add it there.
#
# Tooling is pinned in go.mod via `tool` directives and run with `go tool`, so
# there is nothing to install globally and every developer gets the same
# versions.

.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

BINARY  := widget-svc
CMD     := ./cmd/$(BINARY)
BIN_DIR := bin

.PHONY: help run build test test-integration lint fmt config clean

help: ## Show this help
	@printf '\n\033[1m%s\033[0m — %s\n\n' "$(BINARY)" "Go service"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@printf '\n'

run: ## Boot the service
	@go run $(CMD)

build: ## Build the runnable artifact into bin/
	@mkdir -p $(BIN_DIR)
	@go build -o $(BIN_DIR)/$(BINARY) $(CMD)
	@echo "built $(BIN_DIR)/$(BINARY)"

test: ## Run unit tests with a coverage summary
	@go test -cover ./...

test-integration: ## Run integration tests (build tag: integration)
	@go test -tags=integration -count=1 ./...

lint: ## Lint, vet, and check that only internal/config reads the environment
	@go vet ./...
	@go tool golangci-lint run ./...
	@$(MAKE) --no-print-directory lint-config-discipline

fmt: ## Format the source in place
	@go tool gofumpt -l -w .

config: ## Print the effective configuration and where each value came from
	@go run $(CMD) --print-config

clean: ## Remove build artifacts
	@rm -rf $(BIN_DIR)
	@echo "cleaned"

# Configuration must be read in exactly one place, or `make config` stops
# telling the truth and a value can arrive from somewhere undocumented.
#
# internal/logging is the one allowed exception: NO_COLOR is a terminal
# convention about the output stream, not service configuration.
.PHONY: lint-config-discipline
lint-config-discipline:
	@if grep -rn --include='*.go' -E 'os\.(Getenv|LookupEnv|Environ)' \
		--exclude-dir=internal/config . \
		| grep -v '_test\.go' \
		| grep -v 'internal/logging/logging.go.*NO_COLOR'; then \
		echo ""; \
		echo "error: environment variables must only be read in internal/config"; \
		exit 1; \
	fi
	@echo "config discipline ok"
