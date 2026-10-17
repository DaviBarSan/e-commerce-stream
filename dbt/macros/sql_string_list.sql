{# sql_string_list(['1', '2']) renders '1', '2' for an IN (...) list. #}
{% macro sql_string_list(values) -%}
    {%- for value in values -%}
        '{{ value }}'{{ ', ' if not loop.last }}
    {%- endfor -%}
{%- endmacro %}
