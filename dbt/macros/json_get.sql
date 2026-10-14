{#
  json_get(column, path, type): read one value from a JSON column (D12, spec 06 §4).
  `path` is dotted ('properties.unit_price.amount_minor'); `type` is a portable name:
  string, integer, bigint, numeric or boolean. A missing path gives NULL.
  This is the only place with dialect-specific JSON syntax.
#}
{% macro json_get(column, path, type='string') -%}
    {{ return(adapter.dispatch('json_get')(column, path, type)) }}
{%- endmacro %}

{% macro postgres__json_get(column, path, type) -%}
    {%- set types = {'string': 'text', 'integer': 'integer', 'bigint': 'bigint', 'numeric': 'numeric', 'boolean': 'boolean'} -%}
    {%- if type not in types -%}
        {{ exceptions.raise_compiler_error("json_get: unsupported type '" ~ type ~ "'") }}
    {%- endif -%}
    {%- set pg_path = '{' ~ (path.split('.') | join(',')) ~ '}' -%}
    cast(({{ column }} #>> '{{ pg_path }}') as {{ types[type] }})
{%- endmacro %}

{% macro bigquery__json_get(column, path, type) -%}
    {%- set types = {'string': 'STRING', 'integer': 'INT64', 'bigint': 'INT64', 'numeric': 'NUMERIC', 'boolean': 'BOOL'} -%}
    {%- if type not in types -%}
        {{ exceptions.raise_compiler_error("json_get: unsupported type '" ~ type ~ "'") }}
    {%- endif -%}
    safe_cast(json_value({{ column }}, '$.{{ path }}') as {{ types[type] }})
{%- endmacro %}
