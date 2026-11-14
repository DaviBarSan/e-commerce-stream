-- Per order, the summed line amounts equal the purchase event's order total (spec 06 §7). A purchase with
-- no lines (its cart events missing) fails too. Reads only fct_orders, so selecting upstream models alone
-- (for example `--select +staging`) never runs it against a stale mart.
select order_id, order_total_minor, purchase_total_minor
from {{ ref('fct_orders') }}
where order_total_minor is null
    or order_total_minor <> purchase_total_minor
