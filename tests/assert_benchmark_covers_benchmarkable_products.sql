with coverage as (
    select min(benchmark_week) as first_covered_week
    from {{ ref('stg_fuel_prices') }}
)

select
    benchmark.product_name,
    count(*) as unmatched_rows,
    min(benchmark.delivered_date_key) as earliest_unmatched
from {{ ref('fct_price_benchmark') }} as benchmark
cross join coverage
where benchmark.is_benchmarked
  and benchmark.market_price is null
  and benchmark.delivered_date_key >= coverage.first_covered_week
group by benchmark.product_name