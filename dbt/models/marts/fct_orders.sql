-- Order rollup (spec 06 §5.3): one row per purchase event. order_total_minor and the counts are summed
-- from fct_order_lines; purchase_total_minor is the purchase event's own total, kept so the two can be
-- reconciled from this table alone (assert_order_lines_match_purchase_total).
with purchases as (

    select
        events.order_id,
        events.cart_id,
        events.user_id,
        events.event_ts as ordered_at,
        checkout.order_total_minor as purchase_total_minor,
        checkout.currency as purchase_currency
    from {{ ref('stg_events__checkout') }} as checkout
    inner join {{ ref('stg_clickstream') }} as events
        on checkout.event_id = events.event_id
    where checkout.action = 'purchase'

),

lines as (

    select
        order_id,
        max(session_key) as session_key,
        count(*) as items_count,
        sum(quantity) as units,
        sum(line_total_minor) as order_total_minor,
        max(currency) as currency
    from {{ ref('fct_order_lines') }}
    group by order_id

)

select
    purchases.order_id,
    purchases.cart_id,
    purchases.user_id,
    lines.session_key,
    purchases.ordered_at,
    cast(purchases.ordered_at as date) as date_day,
    coalesce(lines.items_count, 0) as items_count,
    coalesce(lines.units, 0) as units,
    lines.order_total_minor,
    purchases.purchase_total_minor,
    coalesce(lines.currency, purchases.purchase_currency) as currency
from purchases
left join lines
    on purchases.order_id = lines.order_id
