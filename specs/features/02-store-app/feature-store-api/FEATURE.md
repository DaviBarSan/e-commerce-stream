# F02.1: Store API (FastAPI) with Telemetry

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Done | [02](../../../02-store-app.md) | T3.1–T3.3 | infra-local-resources, telemetry-producer | 3 |

## 1. Goal
A stateless FastAPI store backend on top of the `store` database. It serves the catalog, search, cart and checkout, and **emits exactly one clickstream event per tracked action** through `EventProducer`. It delivers the backend half of journey 1 (`PLAN.md` §9).

## 2. Scope
- **In:**
  - The store schema (created by SQLAlchemy, no migration tool) and an idempotent seed
  - Every endpoint in spec 02 §6
  - The request headers: `X-Session-Id`, `X-User-Id`, `Idempotency-Key`, `X-Page-Url`
  - Telemetry hooks
  - OpenAPI docs
- **Out:**
  - The UI (`store-frontend`)
  - Containers and Terraform (`store-deploy`)
  - Journey 2–10 behavior, such as payment failures or login (`PLAN.md` §9)

## 3. Implementation definition
- **Packaging:** `services/store_backend` is a **uv workspace member** with its own `pyproject.toml` (FastAPI, uvicorn, SQLAlchemy 2, psycopg 3). It depends on the root package with the `kafka` extra (`clickstream[kafka]`), which is ready for the Docker image in `store-deploy`.
- **Layout:** `services/store_backend/store_backend/{main.py, settings.py, db.py, models.py, identity.py, telemetry_hooks.py, seed.py, routers/}`. The package is named `store_backend`, not `app`, because the services share the root virtual environment and two top-level `app` packages would collide.
- **Database access:** SQLAlchemy 2 (synchronous) with psycopg 3, connecting as `store_app` through `STORE_DB_DSN`.
- **Schema, without a migration tool:**
  - The tables are declared as SQLAlchemy models and created with `metadata.create_all()`, which only creates missing tables. The seed and the app startup both run it.
  - A schema change during local development is applied by recreating the environment (`make down && make up`). A migration tool can be added later if the schema has to evolve with data that must be kept.
- **Tables (spec 02 §5):**

  | Table | Columns |
  |---|---|
  | `products` | `product_id` (PK), `sku` (unique), `name`, `category`, `price_minor` (integer), `currency` (3 letters), `image_url` |
  | `users` | `user_id` (PK), `email` (unique), `created_at`. Identified users only, loaded by the seed. |
  | `carts` | `cart_id` (PK), `session_id`, `user_id`, `status` (`open` / `converted` / `abandoned`), `created_at`, `updated_at`. At most one `open` cart per `session_id`. |
  | `cart_items` | `cart_id` + `product_id` (PK), `quantity`, `unit_price_minor`, `currency` |
  | `orders` | `order_id` (PK), `cart_id` (unique), `user_id` (plain text, no foreign key, so anonymous `anon-…` buyers work), `total_minor`, `currency`, `created_at` |

  Money is always an integer amount in minor units plus a currency, matching the event contract (spec 04 §3.2), so nothing converts floats.
- **Seed:** about 200 products in 8 categories plus a few identified users, sized by configuration and generated deterministically. It upserts on the natural keys (`sku`, `email`), so rerunning it changes nothing.
- **Request headers (`identity.py` middleware):**
  - `X-Session-Id` / `X-User-Id`: read, or created when missing (`s-<uuid>`, `anon-<uuid>`), and echoed in the response headers.
  - `Idempotency-Key`: one per user action (D13). It's generated when missing, and the event's `event_id` is derived from it (`derive_event_id`).
  - `X-Page-Url` (optional): the storefront page the action happened on. Without it, the backend uses a standard storefront path: `/`, `/catalog`, `/search?q=…`, `/products/{id}`, `/cart`, `/checkout`, `/checkout/confirmation`.
- **Carts and checkout:**
  - The first `POST /cart/items` in a session creates its `open` cart.
  - `POST /checkout/start` requires a non-empty open cart.
  - `POST /checkout/complete` creates the order, marks the cart `converted`, and returns the `order_id`. Payment is simulated and always succeeds (payment failures belong to journey 7).
  - Prices always come from the database, never from the client.
- **Telemetry:**
  - **One producer per process:** created in the FastAPI lifespan with `get_producer()`, and closed (which flushes it) at shutdown.
  - A single hook per tracked endpoint builds the event with `build_event` (spec 04 §3–4), filling `session_id`, `user_id`, `page_url`, the join keys (D10) and `properties`, and calls `send_event`. It runs after the database commit, so an event is only emitted for an action that happened.
  - A failed publish is logged and counted by the producer, and **never fails the request** (spec 04 §7).
- **Config:** only contract keys: `STORE_DB_DSN`, `STREAMING_BACKEND` plus the backend's keys, and `EVENTS_TOPIC`.

## 4. Interfaces
- **Consumes:** the `store` database and the `store_app` role (`infra-local-resources`), and the `telemetry` package (`telemetry-producer`).
- **Produces:**
  - The HTTP API on `:8000` (spec 02 §6), used by `store-frontend` and the bots, with OpenAPI at `/docs`
  - Events on `clickstream.events.v1`

## 5. E2E test flows
The flows start the API with uvicorn on the host (`:8000`), as a subprocess using `.env.local`. Running it in a container comes later, in `store-deploy`.

**E2E-1: purchase journey produces orders and events.**
1. Ensure the local environment is up, run the seed, and start the API.
2. Over HTTP, using one session: search → product → add to cart ×2 → checkout start → checkout complete.
3. The `orders` table has one row with the right total, and the cart status is `converted`.
4. Kafka has exactly the expected event sequence (`search`, `product_view`, `add_to_cart`, `add_to_cart`, `checkout_start`, `purchase`), all with the same `session_id` and `user_id`, the D10 join keys, and all valid against the v1 schema.
5. Retrying a request with the same `Idempotency-Key` produces an event with the same `event_id` (D13).

**E2E-2: statelessness and broker outage.**
1. Add an item to the cart, restart the API, then call `GET /cart`. The item is still there.
2. Stop the Kafka container, then call `POST /cart/items`. The response is 2xx and doesn't wait on the broker; the event waits in the producer's queue (spec 04 §7).
3. Start Kafka again and make another call. Both events are delivered: a short outage loses nothing.
4. Rerun the seed. The product count doesn't change.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=store-api`, and `/docs` serves the OpenAPI spec.

## 7. Open items
None. `product_id`, `cart_id` and `order_id` are top-level event fields (D10), and `event_id` is derived from the `Idempotency-Key` header (D13).
