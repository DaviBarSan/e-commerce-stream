-- One row per event type (spec 06 §5.3): the event_catalog seed exposed as a dimension.
select
    event_type,
    family,
    action,
    default_page_type,
    funnel_step,
    is_conversion
from {{ ref('event_catalog') }}
