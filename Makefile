# Mint — the top level. Most targets fan out to both reference services.
#
# The per-service targets are the real interface; see foundry/go-service/Makefile
# and foundry/py-service/Makefile. Every target below exists in both.
#
# The Copier templates minted from these services live in their own repos
# under github.com/dyosmos — see README.md. py-client moved out too, ahead of
# being published the same way.

.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

SERVICES := foundry/go-service foundry/py-service

.PHONY: help test lint fmt build clean compare run-go run-py

help: ## Show this help
	@printf '\n\033[1mMint\033[0m — one API, two languages\n\n'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@printf '\nEach service has the same targets:\n'
	@printf '  make -C foundry/go-service help\n  make -C foundry/py-service help\n\n'

test: ## Run both services' tests
	@$(foreach s,$(SERVICES),printf '\n\033[1m== $(s) ==\033[0m\n' && $(MAKE) --no-print-directory -C $(s) test &&) true

lint: ## Lint both services
	@$(foreach s,$(SERVICES),printf '\n\033[1m== $(s) ==\033[0m\n' && $(MAKE) --no-print-directory -C $(s) lint &&) true

fmt: ## Format both services
	@$(foreach s,$(SERVICES),printf '\n\033[1m== $(s) ==\033[0m\n' && $(MAKE) --no-print-directory -C $(s) fmt &&) true

build: ## Build both services
	@$(foreach s,$(SERVICES),printf '\n\033[1m== $(s) ==\033[0m\n' && $(MAKE) --no-print-directory -C $(s) build &&) true

clean: ## Clean both services
	@$(foreach s,$(SERVICES),$(MAKE) --no-print-directory -C $(s) clean &&) true

compare: ## Boot both services and diff what they return
	@./scripts/compare.sh

run-go: ## Boot the Go service
	@$(MAKE) --no-print-directory -C foundry/go-service run

run-py: ## Boot the Python service
	@$(MAKE) --no-print-directory -C foundry/py-service run
