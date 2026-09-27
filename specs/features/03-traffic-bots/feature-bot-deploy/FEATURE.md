# F03.2: Bot Container & On-Demand Runs

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Not started | [03](../../../03-traffic-bots.md) | T4.3 | F03.1, F02.3 | 4 |

## 1. Goal
Package the bot as an image and run it on demand, managed by Terraform, with `make bot`.

## 2. Scope
- **In:**
  - `services/traffic_bot/Dockerfile`
  - `modules/local/bot`
  - The `make bot` and `make bot-stop` targets, which take the profile, users, duration and seed as overrides
- **Out:** the Cloud Run Job (Phase 8).

## 3. Implementation definition
- **Image:** Locust running headless, with the parameters taken from `BOT_*` environment variables.
- **`modules/local/bot`:**
  - A container on the platform network targeting `http://store-api:8000`.
  - Controlled by a `bot_enabled` variable, which defaults to `false` so `make up` doesn't start traffic.
- **`make bot`:** runs the `apply` with `bot_enabled=true` and the given variables, then follows the container logs until it exits.

## 4. Interfaces
- **Consumes:** the store API container (F02.3).
- **Produces:** traffic, which shows up as events in `clickstream.events.v1`.

## 5. E2E test flows
**E2E-1: on-demand run.**
1. Run `make bot BOT_DURATION=2m`.
2. The container runs, exits 0 after the set duration, and prints a summary.
3. The offsets on `clickstream.events.v1` go up during the run.

**E2E-2: overrides and cleanup.**
1. Run `make bot BOT_PROFILE=promo_spike BOT_USERS=50`. The container environment reflects the overrides.
2. Run `make bot-stop` in the middle of the run. The container is stopped and removed, and the other platform containers aren't touched.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=bot-deploy`.

## 7. Open items
None.
