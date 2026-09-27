# F03.1: Bot Personas & Traffic Profiles

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Not started | [03](../../../03-traffic-bots.md) | T4.1, T4.2 | F02.1 | 4 |

## 1. Goal
Locust-based simulation of the three personas against the store API, with traffic profiles and seeded runs you can repeat.

## 2. Scope
- **In:**
  - The personas: casual browser, high-intent buyer and cart abandoner
  - Think time, returning users and idle gaps (spec 03 §5)
  - The traffic profiles `steady`, `peak_hours` and `promo_spike`
  - Configuration through environment variables
- **Out:**
  - Containers and Terraform (F03.2)
  - Playwright browser mode (optional, not planned)

## 3. Implementation definition
- **Layout:** `services/traffic_bot/{locustfile.py, personas/, profiles/*.yaml}`.
- **Personas:** Locust `User` classes. Their weights come from `BOT_PERSONA_WEIGHTS`, with defaults 60/15/25.
- **Profiles:** custom `LoadTestShape` classes read from YAML.
- **Reproducibility:** `BOT_SEED` sets up a per-user RNG, derived from the seed plus the user index.
- **Identity:** each simulated user creates its own `session_id` and `user_id` headers, and reuses the `user_id` when acting as a returning user.

## 4. Interfaces
- **Consumes:** the store API (`BACKEND_URL`).
- **Produces:** HTTP traffic, which leads the store API to emit events.

## 5. E2E test flows
**E2E-1: mix and volume.**
1. Run the `steady` profile headless against the local API for 5 minutes with a fixed seed.
2. The observed persona mix, counted from journeys, is within ±5% of the configured weights.
3. Kafka receives events of every type.
4. Some sessions contain an idle gap longer than 30 minutes (use a time-compression factor so this happens within the test).

**E2E-2: determinism and profile shape.**
1. Two runs with the same `BOT_SEED` give the same journey sequence (compared as persona + action traces).
2. The `promo_spike` profile gives a peak event rate at least 3× the `steady` baseline, measured from the topic offsets.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=bot-simulation`.

## 7. Open items
- Whether browser mode (Playwright) is needed (spec 03 §10).
