-- Cart fact (spec 06 §5.3): the cart lifecycle as an accumulating snapshot, one row per cart. A cart is
-- converted once purchased; otherwise abandoned when its last activity is more than 30 minutes before the
-- newest event in the warehouse, and open until then. The store's carts.status is not used (D15).
with cart_events as (

    select cart_id, user_id, event_id, event_type, event_ts
    from {{ ref('stg_clickstream') }}
    where cart_id is not null

),

first_adds as (

    select
        cart_events.cart_id,
        cart_events.user_id,
        cart_events.event_ts as created_at,
        sessions.session_key,
        row_number() over (partition by cart_events.cart_id order by cart_events.event_ts, cart_events.event_id)
            as position
    from cart_events
    inner join {{ ref('int_sessions') }} as sessions
        on cart_events.event_id = sessions.event_id
    where cart_events.event_type = 'add_to_cart'

),

checkout_starts as (

    select
        cart_events.cart_id,
        cart_events.event_ts,
        checkout.cart_total_minor,
        checkout.currency,
        row_number() over (partition by cart_events.cart_id order by cart_events.event_ts desc, cart_events.event_id desc)
            as recency
    from cart_events
    inner join {{ ref('stg_events__checkout') }} as checkout
        on cart_events.event_id = checkout.event_id
    where checkout.action = 'start'

),

milestones as (

    select
        cart_id,
        min(case when event_type = 'checkout_start' then event_ts end) as checkout_started_at,
        min(case when event_type = 'purchase' then event_ts end) as purchased_at,
        max(event_ts) as last_activity_at
    from cart_events
    group by cart_id

),

lines as (

    select
        cart_id,
        sum(case when is_removed then 0 else 1 end) as line_count,
        sum(quantity) as unit_count
    from {{ ref('int_cart_lines') }}
    group by cart_id

),

newest as (

    select max(event_ts) as newest_event_at
    from {{ ref('stg_clickstream') }}

)

select
    first_adds.cart_id,
    first_adds.user_id,
    first_adds.session_key,
    first_adds.created_at,
    milestones.checkout_started_at,
    milestones.purchased_at,
    milestones.last_activity_at,
    cast(first_adds.created_at as date) as created_date_day,
    cast(milestones.checkout_started_at as date) as checkout_date_day,
    cast(milestones.purchased_at as date) as purchased_date_day,
    {{ dbt.datediff('first_adds.created_at', 'milestones.checkout_started_at', 'minute') }} as minutes_to_checkout,
    {{ dbt.datediff('first_adds.created_at', 'milestones.purchased_at', 'minute') }} as minutes_to_purchase,
    coalesce(lines.line_count, 0) as line_count,
    coalesce(lines.unit_count, 0) as unit_count,
    checkout_starts.cart_total_minor as checkout_total_minor,
    checkout_starts.currency,
    case
        when milestones.purchased_at is not null then 'converted'
        when {{ dbt.datediff('milestones.last_activity_at', 'newest.newest_event_at', 'second') }} > 1800
            then 'abandoned'
        else 'open'
    end as status
from first_adds
inner join milestones
    on first_adds.cart_id = milestones.cart_id
left join lines
    on first_adds.cart_id = lines.cart_id
left join checkout_starts
    on first_adds.cart_id = checkout_starts.cart_id
    and checkout_starts.recency = 1
cross join newest
where first_adds.position = 1
