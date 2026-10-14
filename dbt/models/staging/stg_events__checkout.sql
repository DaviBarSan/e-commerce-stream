-- Checkout family (spec 06 §5.1): start and purchase. Each amount keeps its own column: the cart total
-- at checkout start and the order total at purchase are never summed together.
select
    event_id,
    event_ts,
    action,
    {{ json_get('payload', 'properties.items_count', 'integer') }} as items_count,
    {{ json_get('payload', 'properties.cart_total.amount_minor', 'bigint') }} as cart_total_minor,
    {{ json_get('payload', 'properties.total.amount_minor', 'bigint') }} as order_total_minor,
    coalesce(
        {{ json_get('payload', 'properties.cart_total.currency') }},
        {{ json_get('payload', 'properties.total.currency') }}
    ) as currency
from {{ ref('stg_clickstream') }}
where family = 'checkout'
