# F02.1: Store API (FastAPI) with Telemetry

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Not started | [02](../../../02-store-app.md) | T3.1–T3.3 | F01.3, F04.2 | 3 |

## 1. Goal
A stateless FastAPI store backend on top of the `store` database. It serves the catalog, search, cart and checkout, and **emits exactly one clickstream event per tracked action** through `EventProducer`.

## 2. Scope
- **In:**
  - The store schema and migrations
  - An idempotent seed
  - Every endpoint in spec 02 §6
  - Handling of the session and user headers
  - Telemetry hooks
  - OpenAPI docs
- **Out:**
  - The UI (F02.2)
  - Containers and Terraform (F02.3)

## 3. Implementation definition
- **Layout:** `services/store_backend/app/{main.py, routers/, models/, db/, telemetry_hooks.py}`, plus `seed/` and `tests/`.
- **Schema:** the `products`, `users`, `carts`, `cart_items` and `orders` tables (spec 02 §5), created with migrations (tool to be chosen when implementing, Alembic suggested).
- **Seed:** about 200 products in 8 categories, set by configuration. It upserts, so rerunning it changes nothing.
- **Identity:**
  - A middleware reads `X-Session-Id` and `X-User-Id`.
  - If they're missing, it creates them (`anon-<uuid>` for the user) and echoes them in the response headers.
- **Telemetry:**
  - A single hook per tracked endpoint builds the `Event` (spec 04 §3–4) and calls `send_event`.
  - A failed publish is logged and counted, and **never fails the request** (spec 04 §7).
- **Config:** `STORE_DB_DSN`, `STREAMING_BACKEND` plus the backend keys, and `EVENTS_TOPIC`.

## 4. Interfaces
- **Consumes:** the `store` database (F01.3) and the `telemetry` package (F04.2).
- **Produces:**
  - The HTTP API on `:8000`, used by F02.2 and F03.1
  - Events on `clickstream.events.v1`

## 5. E2E test flows
**E2E-1: purchase journey produces orders and events.**
1. Seed the database and start the API locally against `.env.local`.
2. Over HTTP, using one session: search → product → add to cart ×2 → checkout start → checkout complete.
3. The `orders` table has one row, and the cart status is `converted`.
4. Kafka has exactly the expected event sequence (`search`, `product_view`, `add_to_cart`, `add_to_cart`, `checkout_start`, `purchase`), all with the same `session_id` and `user_id`, and all valid against the v1 schema.

**E2E-2: statelessness and broker outage.**
1. Add an item to the cart, restart the API, then call `GET /cart`. The item is still there.
2. Stop the Kafka container, then call `POST /cart/items`. The response is 2xx and the publish failure is logged.
3. Start Kafka again. The next action's event is delivered.
4. Rerun the seed. The product count doesn't change.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=F02.1`, and `/docs` serves the OpenAPI spec.

## 7. Open items
- Where `product_id` goes in events (parking lot). Until then it stays in `metadata_json`.
