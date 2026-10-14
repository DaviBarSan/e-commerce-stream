-- Raw events whose schema_version staging doesn't accept (spec 06 §5.1). They stay in raw, out of
-- staging, and this test reports them as a warning without failing the build.
{{ config(severity='warn') }}

select
    raw_events.event_id,
    raw_events.schema_version
from {{ source('raw', 'clickstream_events') }} as raw_events
left join {{ ref('stg_clickstream') }} as staged
    on raw_events.event_id = staged.event_id
where staged.event_id is null
    and raw_events.schema_version not in ({{ sql_string_list(var('supported_schema_versions')) }})
