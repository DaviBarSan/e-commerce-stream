-- One row per page type (spec 06 §5.3), from the page_types seed.
select
    page_type,
    funnel_stage,
    sort_order
from {{ ref('page_types') }}
