{#
  sessionize(relation, gap_seconds): the session rule (spec 06 §5.2), shared by int_sessions and the
  boundary fixture test. `relation` needs user_id, event_id and event_ts. A new session starts at a user's
  first event, or when the gap since their previous event is more than `gap_seconds`. Returns every input
  column plus is_new_session, session_seq and session_key. ANSI window functions only.
#}
{% macro sessionize(relation, gap_seconds=1800) -%}
with ordered as (

    select
        *,
        lag(event_ts) over (partition by user_id order by event_ts, event_id) as previous_event_ts
    from {{ relation }}

),

flagged as (

    select
        *,
        case
            when previous_event_ts is null then 1
            when {{ dbt.datediff('previous_event_ts', 'event_ts', 'second') }} > {{ gap_seconds }} then 1
            else 0
        end as is_new_session
    from ordered

),

numbered as (

    select
        *,
        sum(is_new_session) over (
            partition by user_id
            order by event_ts, event_id
            rows between unbounded preceding and current row
        ) as session_seq
    from flagged

)

select
    *,
    {{ dbt_utils.generate_surrogate_key(['user_id', 'session_seq']) }} as session_key
from numbered
{%- endmacro %}
