# [[ service_name ]] — minted from Mint.
#
# The target names, descriptions, argument shapes and output style in this
# file are IDENTICAL to the Go template's Makefile by requirement, not by
# coincidence. `make parity` in the mint repo diffs `make help` between a
# generated Go service and a generated Python service and fails on any
# difference beyond the service name. If you add a target here, add it there.

.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

PKG := [[ package_name ]]

# Unimplemented targets fail loudly and name the mint chunk that delivers
# them. A stub that exits 0 would eventually be mistaken for a passing check.
define todo
	@printf '\033[33mmake %s\033[0m is not implemented yet — delivered by mint chunk %s\n' "$(1)" "$(2)"
	@exit 1
endef

.PHONY: help run build test test-integration lint fmt config agents-docs clean

help: ## Show this help
	@printf '\n[[ service_name ]] — [[ service_description ]]\n\n'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@printf '\nDocs: AGENTS.md · docs/ · http://localhost:[[ port ]]/llms.txt\n\n'

run: ## Run the service locally
	@# `python -m` and NOT the uvicorn CLI. The CLI calls configure_logging()
	@# before importing the app, installing non-propagating handlers that no
	@# in-app configuration can reclaim — the service would ship two log
	@# formats. See ADR 0010.
	@uv run python -m $(PKG)

build: ## Build the distributable artifact
	@uv build --quiet
	@printf 'built dist/\n'

test: ## Run unit tests with coverage
	$(call todo,test,07)

test-integration: ## Run integration tests (needs external dependencies)
	$(call todo,test-integration,07)

lint: ## Lint, type-check, and check layer boundaries
	@uv run ruff check .
	@uv run mypy src
	@$(MAKE) --no-print-directory check-boundaries

fmt: ## Format all source in place
	@uv run ruff format .
	@uv run ruff check --fix-only .

config: ## Print effective configuration, secrets masked
	$(call todo,config,03)

agents-docs: ## Regenerate openapi.json, llms.txt, and AGENTS.md's command block
	$(call todo,agents-docs,09)

clean: ## Remove build artifacts
	@rm -rf dist .pytest_cache .mypy_cache .ruff_cache .coverage
	@printf 'cleaned\n'

# --- internal targets (no ## comment, so they stay out of `make help`) ---

.PHONY: check-boundaries
check-boundaries:
	@# Nothing outside internal/transport/http may import FastAPI request
	@# types. Chunk 07 replaces this with the full layer-boundary check.
	@! grep -rn --include='*.py' -E '^\s*from fastapi import|^\s*import fastapi' \
		src --exclude-dir=http \
		|| { printf '\033[31mlayer violation:\033[0m fastapi imported outside internal/transport/http\n'; exit 1; }
