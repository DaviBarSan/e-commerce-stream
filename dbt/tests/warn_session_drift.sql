-- Drift check (spec 06 §7): derived sessions per distinct client session_id should stay within 0.5–3.
-- A large drift usually means a client isn't sending X-Session-Id or the session rule needs review.
-- Reported as a warning; it never fails the build.
{{ config(severity='warn') }}

with counts as (

    select
        count(distinct session_key) as derived_sessions,
        count(distinct client_session_id) as client_sessions
    from {{ ref('int_sessions') }}

)

select derived_sessions, client_sessions
from counts
where client_sessions > 0
    and (derived_sessions * 1.0 / client_sessions < 0.5 or derived_sessions * 1.0 / client_sessions > 3)
