-- Only diesel has an EIA retail benchmark, so other products are expected to
-- carry a null market price. A diesel row missing one means the price feed
-- stopped, the product naming drifted, or the as-of join broke -- and the
-- margin figures would quietly be computed on fewer rows than the reader
-- assumes.
select
    product_name,
    count(*) as unmatched_rows
from {{ ref('fct_price_benchmark') }}
where is_benchmarked
  and market_price is null
group by product_name
