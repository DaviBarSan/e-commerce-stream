-- Sales fact (spec 06 §5.3): one row per product in one order, from each purchase's cart (its lines that
-- weren't removed). order_id is a degenerate dimension. Money is additive only within a currency.
with purchases as (

    select
        events.order_id,
        events.cart_id,
        events.user_id,
        events.event_ts as ordered_at,
        sessions.session_key
    from {{ ref('stg_clickstream') }} as events
    inner join {{ ref('int_sessions') }} as sessions
        on events.event_id = sessions.event_id
    where events.event_type = 'purchase'

)

select
    purchases.order_id,
    lines.product_id,
    purchases.cart_id,
    purchases.user_id,
    purchases.session_key,
    purchases.ordered_at,
    cast(purchases.ordered_at as date) as date_day,
    cast(extract(hour from purchases.ordered_at) as {{ dbt.type_int() }}) as hour_of_day,
    lines.quantity,
    lines.unit_price_minor,
    lines.quantity * lines.unit_price_minor as line_total_minor,
    lines.currency
from purchases
inner join {{ ref('int_cart_lines') }} as lines
    on purchases.cart_id = lines.cart_id
where not lines.is_removed
