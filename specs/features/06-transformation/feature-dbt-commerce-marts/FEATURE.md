# F06.3: dbt Commerce Marts (carts, orders, products)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Not started | [06](../../../06-transformation.md) | T6.6 | dbt-sessions-funnel, store-outbox | 6 |

## 1. Goal
Complete the dimensional model (D14) with the cart and sales processes: the cart lifecycle as an accumulating snapshot, the sales transaction fact at order-line grain and the product dimension. Prove that the warehouse agrees with the store database, its system of record (D15).

### What it builds
- **`int_cart_lines`**: each cart's final contents, rebuilt from cart events.
- **`dim_products`**, **`fct_carts`**, **`fct_order_lines`** and the **`fct_orders`** rollup.
- **A reconciliation check** between `marts.fct_orders` and `store.orders`.

## 2. Scope
- **In:** the models above, with the tests in spec 06 §7 for them, including the line-total-to-order-total singular test.
- **Out:**
  - Product names and order status from the store database (journey 10, parked)
  - Cart recovery and derived `cart_abandoned` events (journey 3)

## 3. Implementation definition
- **`int_cart_lines`** (incremental on `cart_id`):
  - Reads `stg_events__cart` joined to `stg_clickstream` for `cart_id`, `product_id` and `user_id`.
  - Per (cart, product): `quantity` is the sum of `add` quantities after the last `remove`, `unit_price_minor` is the latest add's price, and `is_removed` is set when the last action is `remove`.
- **`dim_products`**: one row per `product_id` seen in navigation or cart events, with `category` (latest `product_view`) and the last seen price and currency.
- **`fct_carts`**: one row per `cart_id`, with:
  - `user_id` and `session_key` (the session of the first add)
  - `created_at`, `checkout_started_at` and `purchased_at`, plus `date_day` keys for each (role-playing `dim_date`)
  - `minutes_to_checkout` and `minutes_to_purchase`
  - line and unit counts from `int_cart_lines`, and `checkout_total_minor` / `currency` from the last `start`
  - `status`, using the spec 06 §5.3 rule
- **`fct_order_lines`**:
  - For each `purchase` (via `order_id` and `cart_id`), the non-removed lines of its cart.
  - Columns: `quantity`, `unit_price_minor`, `line_total_minor = quantity * unit_price_minor`, `currency`, `order_id`, `cart_id`, `product_id`, `user_id`, `session_key`, `date_day`, `hour_of_day`.
- **`fct_orders`**: one row per `order_id`, with `items_count`, `units`, `order_total_minor` (summed from the lines) and `currency`.
- **Tests:**
  - Grain keys and bus-matrix relationships (spec 06 §5.4).
  - The singular test: `sum(line_total_minor)` per order equals the purchase event's `order_total_minor`.
  - `minutes_to_* >= 0`.

## 4. Interfaces
- **Consumes:**
  - `stg_clickstream`, `stg_events__cart` and `stg_events__checkout` (`dbt-foundations`)
  - `int_sessions`, `dim_date` and `dim_time_of_day` (`dbt-sessions-funnel`)
  - The guaranteed delivery of state-change events (`store-outbox`)
- **Produces:** in `warehouse.marts`: `dim_products`, `fct_carts`, `fct_order_lines`, `fct_orders`; in `warehouse.intermediate`: `int_cart_lines`.

## 5. E2E test flows
**E2E-1: carts and orders from a real journey.**
1. Through the API, run:
   - a session that adds a product twice, adds a second product, removes it, adds it again, then purchases;
   - a second session that adds a product and stops.
2. Ingest the events and run `make dbt ARGS=build`; everything passes.
3. `fct_order_lines` has exactly the purchased lines, with the right quantities and amounts, and `fct_orders.order_total_minor` equals the purchase event's total.
4. `fct_carts` shows the first cart as `converted`, with its milestone timestamps. After the test moves the clock past 30 minutes (a later event from another user), the second cart shows as `abandoned`.

**E2E-2: reconciliation with the system of record.**
1. Stop Kafka, complete two purchases through the API (they wait in the outbox), and start Kafka again.
2. Ingest the events and run `make dbt ARGS=build`.
3. For every order, `marts.fct_orders` (count, `order_id`, `order_total_minor`, `currency`) equals `store.orders`, read through `STORE_DB_DSN`. Nothing was lost during the outage.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=dbt-commerce-marts`, and the `dbt-sessions-funnel` flows still pass.

## 7. Open items
None.
