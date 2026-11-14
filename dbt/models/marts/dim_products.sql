-- One row per product seen in events (spec 06 §5.3): the category from the latest product view and the
-- last seen price. Names arrive only with store data (journey 10). Type 1, recomputed on every build.
with product_events as (

    select
        events.product_id,
        events.event_id,
        events.event_ts,
        navigation.product_category as category,
        coalesce(navigation.product_price_minor, cart.unit_price_minor) as price_minor,
        coalesce(navigation.currency, cart.currency) as currency
    from {{ ref('stg_clickstream') }} as events
    left join {{ ref('stg_events__navigation') }} as navigation
        on events.event_id = navigation.event_id
    left join {{ ref('stg_events__cart') }} as cart
        on events.event_id = cart.event_id
    where events.product_id is not null

),

latest_categories as (

    select
        product_id,
        category,
        row_number() over (partition by product_id order by event_ts desc, event_id desc) as recency
    from product_events
    where category is not null

),

latest_prices as (

    select
        product_id,
        price_minor,
        currency,
        row_number() over (partition by product_id order by event_ts desc, event_id desc) as recency
    from product_events
    where price_minor is not null

),

seen as (

    select product_id, min(event_ts) as first_seen_at, max(event_ts) as last_seen_at
    from product_events
    group by product_id

)

select
    seen.product_id,
    latest_categories.category,
    latest_prices.price_minor as last_price_minor,
    latest_prices.currency,
    seen.first_seen_at,
    seen.last_seen_at
from seen
left join latest_categories
    on seen.product_id = latest_categories.product_id
    and latest_categories.recency = 1
left join latest_prices
    on seen.product_id = latest_prices.product_id
    and latest_prices.recency = 1
