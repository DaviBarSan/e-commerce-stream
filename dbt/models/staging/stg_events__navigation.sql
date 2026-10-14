-- Navigation family (spec 06 §5.1): page_view, search and product_view, with their properties typed.
select
    event_id,
    event_ts,
    action,
    {{ json_get('payload', 'properties.page') }} as page,
    {{ json_get('payload', 'properties.query') }} as search_query,
    {{ json_get('payload', 'properties.results_count', 'integer') }} as search_results_count,
    {{ json_get('payload', 'properties.category') }} as product_category,
    {{ json_get('payload', 'properties.price.amount_minor', 'bigint') }} as product_price_minor,
    {{ json_get('payload', 'properties.price.currency') }} as currency
from {{ ref('stg_clickstream') }}
where family = 'navigation'
