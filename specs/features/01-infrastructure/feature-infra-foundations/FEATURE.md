# F01.1: Repository & Tooling Foundations

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Not started | [01](../../../01-infrastructure.md) | T0.1–T0.5 | none | 0 |

## 1. Goal
Set up the repository skeleton, pinned tool versions, the Makefile interface and git hygiene that every later feature builds on.

## 2. Scope
- **In:**
  - The directory tree
  - `versions.env`
  - The Makefile with every target from spec 01 §9, plus `make e2e FEATURE=`
  - `.gitignore`
  - The Windows prerequisites in the README
- **Out:** any Terraform resources (F01.2 and later).

## 3. Implementation definition
- **Directories:**
  - `terraform/modules/{local,gcp,aws}`, `terraform/envs/{local/10-platform,local/20-resources,gcp,aws}`
  - `services/`, `telemetry/`, `dbt/`, `dags/`, `scripts/smoke/`, `tests/e2e/`
- **`versions.env`:**
  - Tools: Terraform, `uv`, Python
  - Images: `apache/kafka`, `postgres`, `provectuslabs/kafka-ui`
  - Providers: `kreuzwerker/docker`, `Mongey/kafka`, `cyrilgdn/postgresql`
- **`Makefile`:**
  - Targets: `help`, `doctor`, `init`, `plan`, `up`, `down`, `env`, `smoke`, `e2e`, `fmt`, `validate`
  - `ENV ?= local`, and `FEATURE` is required for `e2e`
  - Runs under Git Bash
  - Targets whose stacks don't exist yet print "not yet implemented" and exit non-zero
- **`.gitignore`:** `.env*`, `*.tfstate*`, `.terraform/`, `.terraform.lock.hcl` (to be decided: commit it or not), `__pycache__/`, `.venv/`, `dbt/target/`, `dbt/logs/`
- **`README.md`:** prerequisites (Docker Desktop, Git Bash, `make`, Terraform, `uv`) and a quickstart.

## 4. Interfaces
- **Produces:** the `make` command interface and `versions.env`, used by every later feature.

## 5. E2E test flows
**E2E-1: fresh checkout is ready.**
1. Start from a clean clone on a machine that meets the README prerequisites.
2. Run `make doctor`. It exits 0 and prints each tool with the required and found versions.
3. Run `make help`. It lists every target in spec 01 §9 plus `e2e`.

**E2E-2: guardrails.**
1. Put a stub earlier in `PATH` that reports a wrong Terraform version, then run `make doctor`. It exits non-zero and names Terraform along with the required and found versions.
2. Create the dummy files `.env.local`, `terraform/envs/local/10-platform/terraform.tfstate` and `.terraform/`.
3. `git status --porcelain` shows none of them.

## 6. Definition of done
Both E2E flows pass through `make e2e FEATURE=F01.1`, and the README quickstart works up to `make doctor`.

## 7. Open items
None.
