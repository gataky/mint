# The target names, their behavior, and their output are the contract this
# service shares with the Go service. Jumping between the two should feel
# identical. If you add a target here, add it there.
#
# Tooling is pinned in pyproject.toml's dev dependency group and run with
# `uv run`, so there is nothing to install globally and every developer gets the
# same versions.

.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

BINARY  := widget-svc
PACKAGE := widget_svc
BIN_DIR := bin

.PHONY: help run build test test-integration lint fmt config clean

help: ## Show this help
	@printf '\n\033[1m%s\033[0m — %s\n\n' "$(BINARY)" "Python service"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@printf '\n'

run: ## Boot the service
	@uv run python -m $(PACKAGE)

build: ## Build the runnable artifact into bin/
	@mkdir -p $(BIN_DIR)
	@uv build --wheel --out-dir $(BIN_DIR) >/dev/null
	@echo "built $$(ls $(BIN_DIR)/*.whl | tail -1)"

test: ## Run unit tests with a coverage summary
	@uv run pytest --cov --cov-report=term-missing

test-integration: ## Run integration tests (pytest mark: integration)
	@uv run pytest -m integration

lint: ## Lint, type-check, and check that only config.py reads the environment
	@uv run ruff check .
	@uv run ruff format --check .
	@uv run mypy
	@$(MAKE) --no-print-directory lint-config-discipline

fmt: ## Format the source in place
	@uv run ruff format .
	@uv run ruff check --fix .

config: ## Print the effective configuration and where each value came from
	@uv run python -m $(PACKAGE) --print-config

clean: ## Remove build artifacts
	@rm -rf $(BIN_DIR) .pytest_cache .mypy_cache .ruff_cache .coverage
	@find . -type d -name __pycache__ -prune -exec rm -rf {} +
	@echo "cleaned"

# Configuration must be read in exactly one place, or `make config` stops
# telling the truth and a value can arrive from somewhere undocumented.
#
# log.py is the one allowed exception: NO_COLOR is a terminal convention about
# the output stream, not service configuration.
.PHONY: lint-config-discipline
lint-config-discipline:
	@if grep -rn --include='*.py' -E 'os\.(environ|getenv)' src \
		--exclude=config.py \
		| grep -v 'log\.py.*NO_COLOR'; then \
		echo ""; \
		echo "error: environment variables must only be read in config.py"; \
		exit 1; \
	fi
	@echo "config discipline ok"
