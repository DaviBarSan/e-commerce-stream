-- The 30-minute session rule on the session_gaps fixture (spec 06 §7): a 29-minute or exact 30-minute
-- gap keeps the session, a 31-minute gap splits it. Runs the same sessionize() macro as int_sessions.
with fixture as (

    select user_id, event_id, event_ts, expected_session_seq
    from {{ ref('session_gaps') }}

),

sessionized as (

    {{ sessionize('fixture') }}

)

select event_id, session_seq, expected_session_seq
from sessionized
where session_seq <> expected_session_seq
