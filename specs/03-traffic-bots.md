# Spec 03: Traffic Bots

> Tasks: T4.1–T4.3, T8.6 (see `PLAN.md`)

## 1. Purpose
Generate realistic synthetic traffic from many users at rates you can control, so the pipeline and the analytics (funnels, sessions, abandonment) have meaningful data.

## 2. Scope
- **In scope:**
  - Persona-driven journeys against the backend API
  - Traffic profiles
  - Reproducibility through seeds
  - Containerized runs
- **Out of scope:** load testing for performance SLOs. Browser-rendered automation is optional (see §8).

## 3. Approach
| Mode | Tool | Use |
|---|---|---|
| **API mode (default)** | Locust | High-volume journeys against the backend API (spec 02 §6) |
| Browser mode (optional) | Playwright Python | A small number of UI-realistic sessions for demos and UI checks |

Because telemetry is emitted by the backend, both modes produce the same events.

## 4. Layout
```
services/traffic_bot/
  personas/      casual_browser.py, high_intent_buyer.py, cart_abandoner.py
  profiles/      steady.yaml, peak_hours.yaml, promo_spike.yaml
  locustfile.py
  Dockerfile
```

## 5. Personas
| Persona | Default weight | Journey |
|---|---|---|
| Casual browser | 60% | home → search 1 item → view 0–2 products → leave |
| High-intent buyer | 15% | search → view 1–3 products → add to cart → checkout start → purchase |
| Cart abandoner | 25% | browse → view products → add 1–3 items → (checkout start in about 50% of cases) → leave |

Behaviour rules:
- **Think time:** randomised per step (default 2–15 s), so the sessionization in spec 06 sees realistic gaps.
- **Returning users:** a configurable share of users reuses a `user_id` in a new `session_id`.
- **Idle gaps:** some users pause for more than 30 minutes in the middle of a journey, to exercise session splitting.

## 6. Traffic profiles
| Profile | Shape |
|---|---|
| `steady` | Constant number of concurrent users |
| `peak_hours` | Daily sine-wave pattern, compressed in time by a configurable factor |
| `promo_spike` | Baseline with a short multiplier burst, which raises the buyer weight |

## 7. Configuration
| Env var | Purpose |
|---|---|
| `BACKEND_URL` | Target API |
| `BOT_PROFILE` | `steady` / `peak_hours` / `promo_spike` |
| `BOT_USERS` / `BOT_SPAWN_RATE` | Concurrency |
| `BOT_DURATION` | How long the run lasts |
| `BOT_PERSONA_WEIGHTS` | Overrides the default persona weights |
| `BOT_SEED` | Makes runs reproducible |

## 8. Deployment
| Env | Runtime |
|---|---|
| Local | Terraform `modules/local/bot`, started on demand with `make bot` (headless Locust) |
| GCP | Cloud Run Job (Phase 8) |

## 9. Acceptance criteria
1. Each persona completes its journey without errors against the local backend.
2. Over a run, the observed persona mix is within ±5% of the configured weights.
3. Different profiles give measurably different event rates in Kafka.
4. Two runs with the same `BOT_SEED` produce the same sequence of journeys.

## 10. Open items
- Whether browser mode (Playwright) is needed at all, or only API mode.
