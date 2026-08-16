# The same target names as the two services, minus the ones a library cannot
# have. Jumping between any two directories in this repo should feel identical.
#
# `run` and `config` are absent on purpose: a library has nothing to boot and no
# configuration of its own to print. Adding stubs that print "n/a" would make
# `make help` lie about what exists.

.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

PACKAGE := mint_client
BIN_DIR := bin

.PHONY: help build test test-integration lint fmt clean

help: ## Show this help
	@printf '\n\033[1m%s\033[0m — %s\n\n' "mint-client" "outbound HTTP client library"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@printf '\n'

build: ## Build the wheel into bin/
	@mkdir -p $(BIN_DIR)
	@uv build --wheel --out-dir $(BIN_DIR) >/dev/null
	@echo "built $$(ls $(BIN_DIR)/*.whl | tail -1)"

test: ## Run unit tests with a coverage summary
	@uv run pytest --cov --cov-report=term-missing

test-integration: ## Run integration tests (pytest mark: integration)
	@uv run pytest -m integration

lint: ## Lint, type-check, and check that the library reads no configuration
	@uv run ruff check .
	@uv run ruff format --check .
	@uv run mypy
	@$(MAKE) --no-print-directory lint-config-discipline
	@$(MAKE) --no-print-directory lint-sdk-discipline

fmt: ## Format the source in place
	@uv run ruff format .
	@uv run ruff check --fix .

clean: ## Remove build artifacts
	@rm -rf $(BIN_DIR) .pytest_cache .mypy_cache .ruff_cache .coverage
	@find . -type d -name __pycache__ -prune -exec rm -rf {} +
	@echo "cleaned"

# The services allow exactly one env reader, in config.py. A library gets zero.
#
# Reading the environment here would put a value into a service's behavior that
# its own `make config` could not name the source of — defeating that rule from
# outside the tree it checks.
.PHONY: lint-config-discipline
lint-config-discipline:
	@if grep -rn --include='*.py' -E 'os\.(environ|getenv)' src; then \
		echo ""; \
		echo "error: a library must not read the environment — take config as an argument"; \
		exit 1; \
	fi
	@echo "config discipline ok"

# A library records spans against whatever provider the application installed.
# Importing the SDK would let it drag in a second tracer implementation, and
# would imply it may configure one. py-service owns the provider.
.PHONY: lint-sdk-discipline
lint-sdk-discipline:
	@if grep -rn --include='*.py' 'opentelemetry\.sdk' src; then \
		echo ""; \
		echo "error: the library depends on the OpenTelemetry API, never the SDK"; \
		exit 1; \
	fi
	@echo "sdk discipline ok"
