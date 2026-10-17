-- Browsing fact (spec 06 §5.3): one row per event, factless (the measure is the row count). Shared
-- columns and dimension keys only; type-specific properties stay in the staging family models.
select
    sessions.event_id,
    sessions.event_ts,
    cast(sessions.event_ts as date) as date_day,
    cast(extract(hour from sessions.event_ts) as {{ dbt.type_int() }}) as hour_of_day,
    sessions.user_id,
    sessions.session_key,
    sessions.client_session_id,
    sessions.event_type,
    sessions.page_type,
    events.product_id,
    events.cart_id,
    events.order_id
from {{ ref('int_sessions') }} as sessions
inner join {{ ref('stg_clickstream') }} as events
    on sessions.event_id = events.event_id
