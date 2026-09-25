-- The as-of join must never match a delivery to a price published after it.
-- Doing so would mean comparing a past sale to a future market, which reads
-- as a pricing insight and is actually a time-travel bug.
select
    delivery_key,
    delivered_date_key,
    benchmark_week
from {{ ref('fct_price_benchmark') }}
where benchmark_week > delivered_date_key
