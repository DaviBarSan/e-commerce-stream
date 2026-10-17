-- One row per event with its derived session (spec 06 §5.2): a new session after 30 minutes of
-- inactivity per user. The client session_id is kept as client_session_id for comparison only.
-- Incremental runs recompute every event of each user who has new events, so session_seq stays a
-- deterministic running count over the user's whole history.
{{ config(materialized='incremental', unique_key='event_id') }}

with events as (

    select
        event_id,
        user_id,
        session_id as client_session_id,
        event_type,
        page_type,
        event_ts,
        ingested_at
    from {{ ref('stg_clickstream') }}
    {% if is_incremental() %}
    where user_id in (
        select distinct user_id
        from {{ ref('stg_clickstream') }}
        where ingested_at > (select max(ingested_at) from {{ this }})
    )
    {% endif %}

),

sessionized as (

    {{ sessionize('events') }}

)

select
    event_id,
    user_id,
    client_session_id,
    event_type,
    page_type,
    event_ts,
    ingested_at,
    is_new_session,
    session_seq,
    session_key
from sessionized
