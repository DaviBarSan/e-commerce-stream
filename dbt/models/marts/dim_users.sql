-- One row per user_id (spec 06 §5.3). Type 1: recomputed from the full event history on every build.
select
    user_id,
    case when user_id like 'anon-%' then true else false end as is_anonymous,
    min(event_ts) as first_seen_at,
    max(event_ts) as last_seen_at,
    count(distinct session_key) as session_count,
    sum(case when event_type = 'purchase' then 1 else 0 end) as lifetime_orders,
    case when count(distinct session_key) > 1 then true else false end as is_returning
from {{ ref('int_sessions') }}
group by user_id
