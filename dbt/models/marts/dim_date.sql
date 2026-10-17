-- One row per calendar day (spec 06 §5.3), from var('dim_date_start') to a year ahead.
with spine as (

    {{ dbt_utils.date_spine(
        datepart='day',
        start_date="cast('" ~ var('dim_date_start') ~ "' as date)",
        end_date=dbt.dateadd('day', 366, 'current_date')
    ) }}

),

days as (

    select cast(date_day as date) as date_day
    from spine

)

select
    date_day,
    cast(extract(year from date_day) as {{ dbt.type_int() }}) as year,
    cast(extract(month from date_day) as {{ dbt.type_int() }}) as month,
    cast(extract(day from date_day) as {{ dbt.type_int() }}) as day_of_month,
    {{ day_of_week('date_day') }} as day_of_week,
    case when {{ day_of_week('date_day') }} in (6, 7) then true else false end as is_weekend,
    cast({{ dbt.date_trunc('month', 'date_day') }} as date) as month_start
from days
