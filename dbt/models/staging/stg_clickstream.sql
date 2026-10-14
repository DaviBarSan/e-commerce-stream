-- One row per event (spec 06 §5.1): the D11 columns, deduplicated on event_id, with the event's
-- family, action and page type from the event_catalog seed. payload is kept for the family models.
with source as (

    select * from {{ source('raw', 'clickstream_events') }}
    where schema_version in ({{ sql_string_list(var('supported_schema_versions')) }})

),

ranked as (

    select
        *,
        row_number() over (
            partition by event_id
            order by ingested_at, source_partition, source_offset
        ) as row_num
    from source

),

catalog as (

    select * from {{ ref('event_catalog') }}

)

select
    ranked.event_id,
    ranked.schema_version,
    ranked.event_type,
    ranked.event_ts,
    ranked.produced_at,
    ranked.ingested_at,
    ranked.user_id,
    ranked.anonymous_id,
    ranked.session_id,
    ranked.product_id,
    ranked.cart_id,
    ranked.order_id,
    {{ json_get('ranked.payload', 'page_url') }} as page_url,
    coalesce(catalog.default_page_type, {{ json_get('ranked.payload', 'properties.page') }}) as page_type,
    catalog.family,
    catalog.action,
    ranked.payload
from ranked
-- left join: an unmapped event type stays visible and fails the relationships test
left join catalog
    on ranked.event_type = catalog.event_type
where ranked.row_num = 1
