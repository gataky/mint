# Mint — the top level. Most targets fan out to both reference services; `mint`
# and `verify` are about the Copier templates under templates/.
#
# The per-service targets are the real interface; see foundry/go-service/Makefile
# and foundry/py-service/Makefile. Every target below exists in both.

.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

SERVICES := foundry/go-service foundry/py-service

# Pinned rather than resolved, so two developers minting on different days get
# the same Copier.
COPIER := uvx copier@9.17.1

.PHONY: help test lint fmt build clean compare run-go run-py mint verify

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

mint: ## Mint a new service from the template (DEST=../my-svc)
	@test -n "$(DEST)" || { echo "usage: make mint DEST=../my-svc"; exit 1; }
	@$(COPIER) copy --trust . "$(DEST)"

# ONLY, not LANG or LANGUAGE: both of those are locale variables make imports
# from the environment, so the target would silently verify "en_US.UTF-8".
verify: ## Generate from the templates, then build, test, lint and boot them (ONLY=go|py)
	@./scripts/verify-template.sh $(ONLY)

run-go: ## Boot the Go service
	@$(MAKE) --no-print-directory -C foundry/go-service run

run-py: ## Boot the Python service
	@$(MAKE) --no-print-directory -C foundry/py-service run
