-- Cart family (spec 06 §5.1): add and remove. quantity is the units added; a remove deletes the whole
-- line and carries no properties.
select
    event_id,
    event_ts,
    action,
    {{ json_get('payload', 'properties.quantity', 'integer') }} as quantity,
    {{ json_get('payload', 'properties.unit_price.amount_minor', 'bigint') }} as unit_price_minor,
    {{ json_get('payload', 'properties.unit_price.currency') }} as currency
from {{ ref('stg_clickstream') }}
where family = 'cart'
