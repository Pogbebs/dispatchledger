-- Only diesel has an EIA retail benchmark, so other products are expected to
-- carry a null market price.
--
-- The window matters: the pipeline fetches a bounded history, so deliveries
-- older than the first published week it loaded have nothing to match against
-- and are legitimately unpriced. Flagging those would make this test fail on
-- every fresh install, and a test that always fails gets muted rather than
-- read.
--
-- Inside the covered window, a diesel row with no market price is a real
-- defect: the feed stopped mid-series, the product naming drifted, or the
-- as-of join broke -- and the margin figures would quietly be computed on
-- fewer rows than the reader assumes.
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