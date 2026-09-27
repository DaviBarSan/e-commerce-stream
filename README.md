# Clickstream Pipeline

A cloud-agnostic clickstream analytics pipeline: an e-commerce store and traffic bots produce events, which stream through a broker into a warehouse, where dbt builds sessions, funnels and a star schema. Everything is provisioned with Terraform, local first.

- Plan and decisions: [`PLAN.md`](PLAN.md)
- Layer specs: [`specs/`](specs/)
- Contributor rules: [`CLAUDE.md`](CLAUDE.md)

## Prerequisites (Windows)

| Tool | Version | Install |
|---|---|---|
| Docker Desktop | see `versions.env` (minimum) | https://www.docker.com/products/docker-desktop, then start it |
| Git for Windows (Git Bash) | any recent | https://git-scm.com/download/win |
| GNU make | see `versions.env` (minimum) | `winget install ezwinports.make` |
| Terraform | see `versions.env` (exact) | `winget install Hashicorp.Terraform` |
| uv | see `versions.env` (minimum) | `winget install astral-sh.uv` |
| Python | see `versions.env` (minimum) | `uv python install 3.12` or python.org |

Notes:
- Run every `make` command from **Git Bash**.
- After installing tools with winget, **open a new terminal** so the updated `PATH` is picked up.
- On Windows `python3` is a Microsoft Store alias. The project uses `python` and `uv run`.

## Quickstart

```bash
git clone <repo-url> e-commerce-stream
cd e-commerce-stream
make doctor   # checks every tool against versions.env
make help     # lists the targets
```

## Commands

| Command | Purpose |
|---|---|
| `make doctor` | Check the tool versions |
| `make up ENV=local` / `make down ENV=local` | Create or destroy an environment |
| `make plan ENV=local` | Show planned infrastructure changes |
| `make env ENV=local` | Write `.env.local` from the Terraform outputs |
| `make smoke ENV=local` | Platform smoke test |
| `make e2e FEATURE=<feature-id>` | Run a feature's two E2E flows (e.g. `FEATURE=infra-foundations`) |
| `make fmt` / `make validate` | Terraform formatting and validation |

`ENV` defaults to `local`. Targets whose Terraform stacks don't exist yet report "not yet implemented".
