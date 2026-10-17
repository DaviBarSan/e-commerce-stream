{# day_of_week(date): ISO day of week, 1 = Monday … 7 = Sunday, on every warehouse. #}
{% macro day_of_week(date) -%}
    {{ return(adapter.dispatch('day_of_week')(date)) }}
{%- endmacro %}

{% macro postgres__day_of_week(date) -%}
    cast(extract(isodow from {{ date }}) as integer)
{%- endmacro %}

{% macro bigquery__day_of_week(date) -%}
    mod(extract(dayofweek from {{ date }}) + 5, 7) + 1
{%- endmacro %}
