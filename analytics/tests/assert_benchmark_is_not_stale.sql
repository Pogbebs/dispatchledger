-- A weekly series should never be more than ~2 weeks behind a delivery.
-- A larger gap means the pipeline stopped loading and every delta after
-- that point is being measured against an old market.
select
    delivery_key,
    delivered_date_key,
    benchmark_week,
    delivered_date_key - benchmark_week as days_stale
from {{ ref('fct_price_benchmark') }}
where delivered_date_key - benchmark_week > 14
