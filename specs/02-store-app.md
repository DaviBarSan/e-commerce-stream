# Spec 02: Store App (Frontend + Backend)

> Tasks: T3.1–T3.6, T8.6 (see `PLAN.md`)

## 1. Purpose
A working e-commerce store that gives realistic user journeys for the clickstream. It is split into a **backend API** and a **frontend UI**, so that:
- **Telemetry is emitted from the backend.** Every event comes from one trusted place, and UI re-runs can't create duplicate events.
- **Bots can call the API directly** for high-volume traffic (spec 03) without rendering the UI.

## 2. Scope
- **In scope:** catalog, search, product detail, cart, checkout (simulated payment), anonymous and identified users, and emitting events through `EventProducer`.
- **Out of scope:** real payments, authentication hardening, inventory reservation and admin screens.

## 3. Architecture
```
[ Browser ] <--ws--> [ Reflex app (UI :3000 + Reflex backend :8001) ] --HTTP--> [ Store API (FastAPI :8000) ] --> [ store DB (Postgres) ]
                                                   │
                                                   └──> EventProducer (spec 04) --> Kafka / Pub/Sub
```

| Component | Tech | Port | Notes |
|---|---|---|---|
| Backend (store API) | Python + FastAPI | 8000 | Stateless; carts are stored in the DB |
| Frontend | Reflex | 3000 (UI), 8001 (Reflex backend) | Reflex event handlers run on the server and call the store API over HTTP. They never touch the DB or emit telemetry. Reflex's backend is moved from its default port 8000 to 8001 so it doesn't clash with the store API. |
| Store DB | Postgres, `store` database | 5432 | Provisioned by spec 01 |

## 4. Layout
```
services/
  store_backend/
    store_backend/  (routers, models, db, telemetry hooks, seed)
    pyproject.toml  (uv workspace member)
    Dockerfile
  store_frontend/
    app/
    pyproject.toml  (uv workspace member)
    Dockerfile
```

## 5. Data model (`store` database)
| Table | Key columns |
|---|---|
| `products` | `product_id`, `sku`, `name`, `category`, `price_minor`, `currency`, `image_url` |
| `users` | `user_id`, `email`, `created_at` |
| `carts` | `cart_id`, `user_id`, `session_id`, `status` (`open` / `converted` / `abandoned`) |
| `cart_items` | `cart_id`, `product_id`, `quantity`, `unit_price_minor`, `currency` |
| `orders` | `order_id`, `cart_id`, `user_id`, `total_minor`, `currency`, `created_at` |

Money is stored as an integer amount in minor units plus a currency, like the event contract (spec 04 §3.2). The tables are created by SQLAlchemy (`metadata.create_all()`), without a migration tool; local schema changes are applied by recreating the environment. The seed is idempotent, and its size is set by configuration (default: about 200 products in 8 categories).

## 6. API (v1)
| Method + path | Purpose | Emits `event_type` |
|---|---|---|
| `GET /products` | List or browse the catalog (paginated, filter by category) | `page_view` (catalog) |
| `GET /search?q=` | Search products | `search` |
| `GET /products/{id}` | Product detail | `product_view` |
| `POST /cart/items` | Add to cart | `add_to_cart` |
| `DELETE /cart/items/{product_id}` | Remove from cart | `remove_from_cart` |
| `GET /cart` | View cart | `page_view` (cart) |
| `POST /checkout/start` | Start checkout | `checkout_start` |
| `POST /checkout/complete` | Place the order | `purchase` |
| `GET /health` | Liveness | none |

### Session and user identity
- Every tracked call carries an `Idempotency-Key` header, one per user action (a retry of the same action reuses it). The backend derives the event's `event_id` from it (D13, spec 04 §3.4), and generates a key when it's missing.
- The client may send `X-Page-Url`, the storefront page the action happened on. Without it, the backend uses a standard storefront path for the endpoint.
- The client sends the `X-Session-Id` and `X-User-Id` headers. The frontend creates them once per browser session, and bots create one per simulated user.
- If they're missing, the backend creates them and returns them in the response headers.
- The canonical list of event types is defined in spec 04.

## 7. Frontend screens
- Home (featured products and categories)
- Search results
- Product detail
- Cart
- Checkout (form and confirmation)

Anything that should be tracked goes through a backend call. The frontend does **not** emit events itself.

## 8. Configuration
Read from the environment contract (spec 01 §4):
- `STORE_DB_DSN`
- `STREAMING_BACKEND` plus the backend-specific keys
- `EVENTS_TOPIC`
- `BACKEND_URL` (frontend only)

## 9. Deployment
| Env | Runtime |
|---|---|
| Local | Terraform `modules/local/app` runs both containers on the platform network |
| GCP | Cloud Run services (Phase 8) |

## 10. Acceptance criteria
1. You can complete a manual purchase through the frontend.
2. Every endpoint in §6 emits exactly one event of the listed type, carrying the correct session and user IDs.
3. The API contract tests pass, and OpenAPI is served at `/docs`.
4. The backend is stateless. Restarting it loses no carts.

## 11. Open items
None. Duplicate events from Reflex reconnects or retried handlers are handled by the `Idempotency-Key` header and the deterministic `event_id` (D13).
