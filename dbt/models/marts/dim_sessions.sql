-- One row per derived session (spec 06 §5.3): its bounds, the client session it started in, and the
-- page types it landed on and exited from.
with ordered as (

    select
        *,
        row_number() over (partition by session_key order by event_ts, event_id) as position_from_start,
        row_number() over (partition by session_key order by event_ts desc, event_id desc) as position_from_end
    from {{ ref('int_sessions') }}

)

select
    session_key,
    max(user_id) as user_id,
    max(case when position_from_start = 1 then client_session_id end) as client_session_id,
    min(event_ts) as session_start_at,
    max(event_ts) as session_end_at,
    max(case when position_from_start = 1 then page_type end) as landing_page_type,
    max(case when position_from_end = 1 then page_type end) as exit_page_type
from ordered
group by session_key
