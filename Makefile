# Developer interface (D6). On Windows, run from Git Bash.
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

include versions.env

ENV ?= local
TF_ENV_DIR := terraform/envs/$(ENV)
# Stacks in apply order; `down` walks them in reverse.
ifeq ($(ENV),local)
STACKS := $(TF_ENV_DIR)/10-platform $(TF_ENV_DIR)/20-resources
else
STACKS := $(TF_ENV_DIR)
endif
REVERSED_STACKS := $(shell printf '%s\n' $(STACKS) | tac)

# Fails with "not yet implemented" until every stack of $(ENV) has Terraform files.
define require_stacks
for s in $(STACKS); do \
  ls $$s/*.tf >/dev/null 2>&1 || { echo "$@: not yet implemented for ENV=$(ENV) (no Terraform in $$s)" >&2; exit 1; }; \
done
endef

.PHONY: help doctor init plan up down env smoke e2e fmt validate

help: ## List the targets
	@echo "Usage: make <target> [ENV=local|gcp|aws] [FEATURE=<feature-id>]   (ENV defaults to local)"
	@grep -hE '^[a-z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-10s %s\n", $$1, $$2}'

doctor: ## Check tool versions against versions.env
	@bash scripts/doctor.sh

init: ## terraform init on every stack of ENV
	@$(require_stacks)
	@for s in $(STACKS); do terraform -chdir=$$s init -input=false; done

plan: ## terraform plan on every stack of ENV
	@$(require_stacks)
	@for s in $(STACKS); do terraform -chdir=$$s plan -input=false; done

up: ## Apply every stack of ENV in order, then write .env.<ENV>
	@$(require_stacks)
	@for s in $(STACKS); do terraform -chdir=$$s init -input=false && terraform -chdir=$$s apply -input=false -auto-approve; done
	@$(MAKE) --no-print-directory env ENV=$(ENV)

down: ## Destroy every stack of ENV in reverse order
	@$(require_stacks)
	@for s in $(REVERSED_STACKS); do terraform -chdir=$$s destroy -input=false -auto-approve; done

env: ## Write .env.<ENV> from the stack outputs
	@echo "env: not yet implemented (arrives with infra-local-resources)" >&2; exit 1

smoke: ## Run the platform smoke test for ENV
	@echo "smoke: not yet implemented (arrives with infra-local-resources)" >&2; exit 1

e2e: ## Run a feature's two E2E flows (FEATURE=<feature-id> required)
	@[ -n "$(FEATURE)" ] || { echo "e2e: FEATURE is required, e.g. make e2e FEATURE=infra-foundations" >&2; exit 1; }
	@[ -d "tests/e2e/$(FEATURE)" ] || { echo "e2e: no flows found in tests/e2e/$(FEATURE)" >&2; exit 1; }
	uv run pytest "tests/e2e/$(FEATURE)" -v

fmt: ## terraform fmt -recursive on terraform/
	terraform fmt -recursive terraform

validate: ## terraform validate on every stack of ENV
	@$(require_stacks)
	@for s in $(STACKS); do terraform -chdir=$$s init -input=false -backend=false >/dev/null && terraform -chdir=$$s validate; done
