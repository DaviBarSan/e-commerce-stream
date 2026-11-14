-- Daily funnel rollup of fct_sessions (spec 06 §5.3): one row per day × landing page type.
select
    date_day,
    landing_page_type,
    count(*) as sessions,
    sum(reached_search) as sessions_reached_search,
    sum(reached_product_view) as sessions_reached_product_view,
    sum(reached_add_to_cart) as sessions_reached_add_to_cart,
    sum(reached_checkout) as sessions_reached_checkout,
    sum(reached_purchase) as sessions_reached_purchase,
    sum(case when is_converted then 1 else 0 end) as converted_sessions
from {{ ref('fct_sessions') }}
group by date_day, landing_page_type
