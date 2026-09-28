# F02.2: Store Frontend (Reflex)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Done | [02](../../../02-store-app.md) | T3.4 | store-api | 3 |

## 1. Goal
A Reflex storefront where you can complete real shopping journeys in the browser. Every tracked action goes through the store API, so each click becomes a contract event (and, with the ingest consumer running, a row in the raw table). The frontend never emits telemetry itself.

### What it builds
- **A storefront on `:3000`** (Reflex production mode: the UI and the Reflex backend share that port) with the journey-1 screens: home (featured products and categories), search results, product detail, cart, checkout form and order confirmation.
- **Identity kept in the browser:** an anonymous `user_id` that survives reloads and later visits (a returning visitor), and a `session_id` per browser tab session. Both go to the API on every call.
- **One `Idempotency-Key` per click**, reused if the call is retried, so a retry never creates a second event (D13).
- **A small API addition:** `GET /home` in `store-api`, so opening the home page emits the journey's first event (`page_view` with `page: home`).

## 2. Scope
- **In:**
  - The screens listed above, with navigation between them
  - Identity and request headers (`X-Session-Id`, `X-User-Id`, `Idempotency-Key`, `X-Page-Url`)
  - `GET /home` in `store-api` (spec 02 §6)
- **Out:**
  - Telemetry emission (the backend does it), authentication, admin screens
  - The Docker image and Terraform (`store-deploy`)
  - Journey 2–10 screens, such as login or checkout steps (`PLAN.md` §9)

## 3. Implementation definition
- **Packaging:** `services/store_frontend` is a uv workspace member (package `store_frontend`) with Reflex (pinned `~=0.9.12`) and httpx. It has **no** dependency on `telemetry` and no database access.
- **Layout:** `services/store_frontend/{rxconfig.py, store_frontend/store_frontend.py (app and pages), store_frontend/state.py, store_frontend/api.py}`.
- **Run:** from `services/store_frontend`: `reflex run --env prod --frontend-port 3000 --backend-port 3000`. Production mode serves the compiled UI and the Reflex backend (websocket) on the **same port**, so `:8001` isn't used. Dev mode (`--env dev`) doesn't work on this Windows setup: the React Router dev server that Reflex generates fails to restart itself under bun (`restartWithMergedOptions() was called, but the process has already been restarted`). On the first run Reflex downloads bun, installs the frontend packages and builds, which takes a few minutes and needs internet access. On Windows, set `PYTHONUTF8=1` when redirecting Reflex's output, or its spinner crashes on the cp1252 console encoding.
- **Config:** `BACKEND_URL`, the store API base URL (spec 02 §8). It's required, with no default; locally it's `http://127.0.0.1:8000`. It becomes a container address in `store-deploy`.
- **Identity (`state.py`):**
  - `user_id` is stored in `rx.LocalStorage` (`anon-<uuid>`, created on the first visit), so it survives reloads and later visits.
  - `session_id` is stored in `rx.SessionStorage` (`s-<uuid>`), one per browser tab session, and survives reloads.
- **API calls (`api.py`):** every call sends `X-Session-Id`, `X-User-Id`, `X-Page-Url` (the current route) and an `Idempotency-Key` created once per user action. A call that fails with a transport error is retried once **with the same key**. The API's HTTP errors (404 / 409) are shown to the user, not retried.
- **Screens and the call each one makes:**

  | Route | Screen | API call on load / action |
  |---|---|---|
  | `/` | Home: featured products, categories, search box | `GET /home` |
  | `/search?q=` | Search results | `GET /search` |
  | `/products/[product_id]` | Product detail, quantity, "Add to cart" | `GET /products/{id}`; action `POST /cart/items` |
  | `/cart` | Cart lines, remove, total, "Checkout" | `GET /cart`; actions `DELETE /cart/items/{id}`, `POST /checkout/start` |
  | `/checkout` | Checkout form (name, email, address; simulated, not stored) | action `POST /checkout/complete` |
  | `/checkout/confirmation` | Order ID and total | none |

- **`GET /home` in `store-api`:** returns up to 8 featured products (the first product of each category) and the category list, and emits `page_view` with `properties.page = "home"`. It's added to spec 02 §6 and to the `store-api` OpenAPI check.
- **Prices** are shown from `price_minor` and `currency`, formatted in the UI. The frontend never sends prices.

## 4. Interfaces
- **Consumes:** the store API (`store-api`) at `BACKEND_URL`.
- **Produces:** the browser UI and its Reflex backend on `:3000`.

## 5. E2E test flows
Both flows are automated with Playwright (headless Chromium), which is test tooling here, not the traffic bot. They start the store API (as in `store-api`) and the Reflex app on the host; the fixture installs Chromium on first use.

**E2E-1: purchase through the UI.**
1. Open `:3000` → search "lamp" → open a product → add to cart → open the cart → checkout → fill the form → confirm.
2. The confirmation page shows an order ID that exists in `store.orders`, with the cart `converted`.
3. Kafka has exactly the matching event sequence: `page_view` (home), `search`, `product_view`, `add_to_cart`, `page_view` (cart), `checkout_start`, `purchase`. All carry the browser's `session_id` and `user_id` and a `page_url` matching the screen.

**E2E-2: session continuity and no duplicate events.**
1. Add an item, reload the page, then go on to the cart.
2. The cart still has the item, and `session_id` and `user_id` haven't changed.
3. Each click produced exactly one event: there is exactly one `add_to_cart` for the item, and the reload created none.
4. Close the browser context and open the store again with the same storage: `user_id` is the same (a returning visitor), and the new tab gets a new `session_id`.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=store-frontend`, and the `store-api` flows still pass (because of `GET /home`).

## 7. Open items
None. The frontend sends one `Idempotency-Key` per user action and reuses it on retries, so duplicates collapse to one `event_id` (D13).
