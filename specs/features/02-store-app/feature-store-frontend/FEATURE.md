# F02.2: Store Frontend (Reflex)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Not started | [02](../../../02-store-app.md) | T3.4 | F02.1 | 3 |

## 1. Goal
A Reflex storefront where you can complete real shopping journeys. Every tracked action goes through the store API, and the frontend never emits telemetry itself.

## 2. Scope
- **In:** the home, search results, product detail, cart and checkout (form and confirmation) screens, and keeping the session and user identity for each browser session.
- **Out:** telemetry emission (the backend does it), authentication and admin screens.

## 3. Implementation definition
- **Layout:** `services/store_frontend/` (a Reflex app: `rxconfig.py`, pages and state).
- **Ports:** Reflex UI on `:3000`, and the Reflex backend on `:8001` (moved off its default 8000).
- **Reflex state:**
  - Holds `session_id` and `user_id`, created once per browser session.
  - Every event handler that calls the store API (via `httpx`, at `BACKEND_URL`) sends them as `X-Session-Id` and `X-User-Id`.
- **No direct DB access and no `telemetry` import** in this service.

## 4. Interfaces
- **Consumes:** the store API (F02.1) and `BACKEND_URL`.
- **Produces:** browser UI on `:3000`.

## 5. E2E test flows
Both flows are automated with Playwright. Playwright is test tooling here, not the traffic bot.

**E2E-1: purchase through the UI.**
1. Open `:3000` → search → open a product → add to cart → checkout → confirm.
2. The confirmation page shows an order ID that exists in `store.orders`.
3. Kafka has the matching event sequence, all with the browser session's `session_id`.

**E2E-2: session continuity and no duplicate events.**
1. Add an item, reload the page, then go on to the cart.
2. The cart still has the item, and `session_id` hasn't changed.
3. The number of events equals the number of tracked API calls. A reload or websocket reconnect creates no extra `add_to_cart`.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=F02.2`.

## 7. Open items
- Avoiding duplicate events on the frontend side (Reflex reconnects and retried handlers). This is in the parking lot; E2E-2 checks the current behavior.
