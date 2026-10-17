-- Session fact (spec 06 §5.3): the journey-1 funnel as an accumulating snapshot, one row per session.
-- The funnel is ordered: step n counts only when it happens at or after step n-1, so the number of
-- sessions reaching each step can never increase down the funnel.
with events as (

    select
        sessions.session_key,
        sessions.event_id,
        sessions.event_type,
        sessions.event_ts,
        catalog.funnel_step
    from {{ ref('int_sessions') }} as sessions
    inner join {{ ref('event_catalog') }} as catalog
        on sessions.event_type = catalog.event_type

),

step_1 as (

    select session_key, min(event_ts) as reached_at
    from events
    where funnel_step = 1
    group by session_key

),

{% for step in range(2, 6) %}
step_{{ step }} as (

    select events.session_key, min(events.event_ts) as reached_at
    from events
    inner join step_{{ step - 1 }} as previous
        on events.session_key = previous.session_key
        and events.event_ts >= previous.reached_at
    where events.funnel_step = {{ step }}
    group by events.session_key

),
{% endfor %}

zero_result_searches as (

    select sessions.session_key, count(*) as zero_result_search_count
    from {{ ref('int_sessions') }} as sessions
    inner join {{ ref('stg_events__navigation') }} as navigation
        on sessions.event_id = navigation.event_id
    where navigation.action = 'search'
        and navigation.search_results_count = 0
    group by sessions.session_key

),

counts as (

    select
        session_key,
        count(*) as event_count,
        sum(case when event_type = 'search' then 1 else 0 end) as search_count,
        sum(case when event_type = 'product_view' then 1 else 0 end) as product_view_count,
        sum(case when event_type = 'add_to_cart' then 1 else 0 end) as add_to_cart_count,
        sum(case when event_type = 'purchase' then 1 else 0 end) as purchase_count
    from events
    group by session_key

)

select
    sessions.session_key,
    sessions.user_id,
    cast(sessions.session_start_at as date) as date_day,
    cast(extract(hour from sessions.session_start_at) as {{ dbt.type_int() }}) as hour_of_day,
    sessions.landing_page_type,
    sessions.exit_page_type,
    sessions.session_start_at,
    sessions.session_end_at,
    {{ dbt.datediff('sessions.session_start_at', 'sessions.session_end_at', 'second') }} as duration_seconds,
    counts.event_count,
    counts.search_count,
    coalesce(zero_result_searches.zero_result_search_count, 0) as zero_result_search_count,
    counts.product_view_count,
    counts.add_to_cart_count,
    step_1.reached_at as first_search_at,
    step_2.reached_at as first_product_view_at,
    step_3.reached_at as first_add_to_cart_at,
    step_4.reached_at as first_checkout_start_at,
    step_5.reached_at as first_purchase_at,
    case when step_1.reached_at is not null then 1 else 0 end as reached_search,
    case when step_2.reached_at is not null then 1 else 0 end as reached_product_view,
    case when step_3.reached_at is not null then 1 else 0 end as reached_add_to_cart,
    case when step_4.reached_at is not null then 1 else 0 end as reached_checkout,
    case when step_5.reached_at is not null then 1 else 0 end as reached_purchase,
    case when counts.purchase_count > 0 then true else false end as is_converted
from {{ ref('dim_sessions') }} as sessions
inner join counts on sessions.session_key = counts.session_key
left join zero_result_searches on sessions.session_key = zero_result_searches.session_key
left join step_1 on sessions.session_key = step_1.session_key
left join step_2 on sessions.session_key = step_2.session_key
left join step_3 on sessions.session_key = step_3.session_key
left join step_4 on sessions.session_key = step_4.session_key
left join step_5 on sessions.session_key = step_5.session_key
