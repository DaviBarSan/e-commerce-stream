-- One row per (cart, product) with the line's final state (spec 06 §5.2): the units added after the
-- line's last remove and the latest unit price. A line whose last action is a remove has quantity 0 and
-- is_removed = true. Incremental runs recompute every line of each cart with new events.
{{ config(materialized='incremental', unique_key=['cart_id', 'product_id']) }}

with cart_events as (

    select
        events.cart_id,
        events.product_id,
        events.user_id,
        events.event_id,
        events.event_ts,
        events.ingested_at,
        cart.action,
        cart.quantity,
        cart.unit_price_minor,
        cart.currency
    from {{ ref('stg_events__cart') }} as cart
    inner join {{ ref('stg_clickstream') }} as events
        on cart.event_id = events.event_id
    {% if is_incremental() %}
    where events.cart_id in (
        select distinct cart_id
        from {{ ref('stg_clickstream') }}
        where family = 'cart'
            and ingested_at > (select max(last_ingested_at) from {{ this }})
    )
    {% endif %}

),

last_removes as (

    select cart_id, product_id, max(event_ts) as removed_at
    from cart_events
    where action = 'remove'
    group by cart_id, product_id

),

latest_adds as (

    select
        cart_id,
        product_id,
        unit_price_minor,
        currency,
        row_number() over (partition by cart_id, product_id order by event_ts desc, event_id desc) as recency
    from cart_events
    where action = 'add'

),

lines as (

    select
        cart_events.cart_id,
        cart_events.product_id,
        max(cart_events.user_id) as user_id,
        sum(
            case
                when cart_events.action = 'add'
                    and (last_removes.removed_at is null or cart_events.event_ts > last_removes.removed_at)
                    then cart_events.quantity
                else 0
            end
        ) as quantity,
        min(cart_events.event_ts) as first_added_at,
        max(cart_events.event_ts) as last_action_at,
        max(cart_events.ingested_at) as last_ingested_at
    from cart_events
    left join last_removes
        on cart_events.cart_id = last_removes.cart_id
        and cart_events.product_id = last_removes.product_id
    group by cart_events.cart_id, cart_events.product_id

)

select
    lines.cart_id,
    lines.product_id,
    lines.user_id,
    lines.quantity,
    latest_adds.unit_price_minor,
    latest_adds.currency,
    case when lines.quantity = 0 then true else false end as is_removed,
    lines.first_added_at,
    lines.last_action_at,
    lines.last_ingested_at
from lines
left join latest_adds
    on lines.cart_id = latest_adds.cart_id
    and lines.product_id = latest_adds.product_id
    and latest_adds.recency = 1
