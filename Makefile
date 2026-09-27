# Developer interface (D6). On Windows, run from Git Bash.
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

include versions.env

# Pinned images reach Terraform as variables.
export TF_VAR_kafka_image    := $(KAFKA_IMAGE)
export TF_VAR_kafka_ui_image := $(KAFKA_UI_IMAGE)
export TF_VAR_postgres_image := $(POSTGRES_IMAGE)

ENV ?= local
TF_ENV_DIR := terraform/envs/$(ENV)
# Stacks in apply order; `down` walks them in reverse.
ifeq ($(ENV),local)
STACKS := $(TF_ENV_DIR)/10-platform $(TF_ENV_DIR)/20-resources
else
STACKS := $(TF_ENV_DIR)
endif
REVERSED_STACKS := $(shell printf '%s\n' $(STACKS) | tac)
# The last stack writes .env.<ENV> (local_sensitive_file.env).
ENV_STACK := $(lastword $(STACKS))
ENV_FILE := .env.$(ENV)

# Fails with "not yet implemented" until every stack of $(ENV) has Terraform files.
define require_stacks
for s in $(STACKS); do \
  ls $$s/*.tf >/dev/null 2>&1 || { echo "$@: not yet implemented for ENV=$(ENV) (no Terraform in $$s)" >&2; exit 1; }; \
done
endef

# tf <stack> <args...>: runs terraform in a stack and retries once. The Mongey/kafka provider
# intermittently fails with "kafka: broker not connected" (a race in its sarama client) even when the
# broker is healthy; plan/apply/destroy are idempotent, so one retry is safe.
define TF
tf() { terraform -chdir="$$1" "$${@:2}" || { echo "terraform: $$1 failed, retrying once in 5s" >&2; sleep 5; terraform -chdir="$$1" "$${@:2}"; }; }
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
	@$(TF); for s in $(STACKS); do tf $$s plan -input=false; done

up: ## Apply every stack of ENV in order (writes .env.<ENV>)
	@$(require_stacks)
	@$(TF); for s in $(STACKS); do terraform -chdir=$$s init -input=false && tf $$s apply -input=false -auto-approve; done
	@echo "up: $(ENV_FILE) written"

down: ## Destroy every stack of ENV in reverse order (full reset)
	@$(require_stacks)
	@$(TF); for s in $(REVERSED_STACKS); do \
	  if ! terraform -chdir=$$s state list 2>/dev/null | grep -q .; then echo "down: $$s has no resources, skipping"; continue; fi; \
	  tf $$s destroy -input=false -auto-approve; \
	done

env: ## Regenerate .env.<ENV> from the stack outputs
	@$(require_stacks)
	@$(TF); tf $(ENV_STACK) apply -input=false -auto-approve -target=local_sensitive_file.env

smoke: ## Run the platform smoke test for ENV
	@[ -f "$(ENV_FILE)" ] || { echo "smoke: $(ENV_FILE) not found; run make up ENV=$(ENV)" >&2; exit 1; }
	uv run python scripts/smoke/smoke.py "$(ENV_FILE)"

e2e: ## Run a feature's two E2E flows (FEATURE=<feature-id> required)
	@[ -n "$(FEATURE)" ] || { echo "e2e: FEATURE is required, e.g. make e2e FEATURE=infra-foundations" >&2; exit 1; }
	@[ -d "tests/e2e/$(FEATURE)" ] || { echo "e2e: no flows found in tests/e2e/$(FEATURE)" >&2; exit 1; }
	uv run pytest "tests/e2e/$(FEATURE)" -v

fmt: ## terraform fmt -recursive on terraform/
	terraform fmt -recursive terraform

validate: ## terraform validate on every stack of ENV, plus modules/aws
	@$(require_stacks)
	@for s in $(STACKS) terraform/modules/aws; do echo "validate: $$s"; terraform -chdir=$$s init -input=false -backend=false >/dev/null && terraform -chdir=$$s validate; done
