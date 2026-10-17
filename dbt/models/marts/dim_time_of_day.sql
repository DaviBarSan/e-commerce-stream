-- One row per hour of the day (spec 06 §5.3), with its day part.
with hours as (

    {{ dbt_utils.generate_series(24) }}

)

select
    generated_number - 1 as hour_of_day,
    case
        when generated_number - 1 < 6 then 'night'
        when generated_number - 1 < 12 then 'morning'
        when generated_number - 1 < 18 then 'afternoon'
        else 'evening'
    end as day_part
from hours
