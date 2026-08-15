# Mint — template source repo.
# These are MINT'S OWN targets. The targets a *generated service* must expose
# are specified in prompt.md § Makefile parity and are a different list.

.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

# Stub helper: fail loudly and name the chunk that implements the target,
# so an unimplemented target is never mistaken for a passing one.
define todo
	@printf '\033[33mmake %s\033[0m is not implemented yet — see tasks/%s\n' "$(1)" "$(2)"
	@exit 1
endef

.PHONY: help parity verify test lint fmt clean

help: ## Show this help
	@printf '\nMint — microservice template generator\n\n'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@printf '\nSpec: prompt.md   Implementation chunks: tasks/README.md\n\n'

parity: ## Check Go and Python templates for drift (8 checks)
	$(call todo,parity,02-copier-scaffolding.md)

verify: ## Generate both templates, build, boot, assert, tear down
	$(call todo,verify,02-copier-scaffolding.md)

test: ## Run mint's own tests
	$(call todo,test,02-copier-scaffolding.md)

lint: ## Lint mint's own scripts and templates
	$(call todo,lint,02-copier-scaffolding.md)

fmt: ## Format mint's own scripts and templates
	$(call todo,fmt,02-copier-scaffolding.md)

clean: ## Remove harness scratch directories
	@rm -rf .mint-tmp
	@echo "cleaned"
