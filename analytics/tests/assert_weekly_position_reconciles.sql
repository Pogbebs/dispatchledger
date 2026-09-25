-- A rollup that does not reconcile with its detail is the most common way an
-- aggregate model lies: a join fans out, a filter drifts, a group-by misses a
-- key, and the summary quietly reports a different business than the table it
-- came from.
--
-- This compares the aggregate against the same rows in fct_price_benchmark,
-- on both money and volume. Rounding to cents and whole gallons absorbs the
-- floating differences of summing in a different order; anything larger is a
-- real divergence.
--
-- It matters more here than for most marts, because agg_weekly_price_position
-- is what the application's Insights page draws. If this drifts, the number a
-- user reads on screen stops matching the deliveries behind it.
with detail as (

    select
        round(sum(margin_vs_benchmark), 2)  as margin,
        round(sum(delivered_gal), 0)        as gallons,
        count(*)                            as deliveries
    from {{ ref('fct_price_benchmark') }}
    where is_benchmarked
      and market_price is not null

),

rollup as (

    select
        round(sum(margin_vs_benchmark), 2)  as margin,
        round(sum(delivered_gal), 0)        as gallons,
        sum(delivery_count)                 as deliveries
    from {{ ref('agg_weekly_price_position') }}

)

select
    detail.margin      as detail_margin,
    rollup.margin      as rollup_margin,
    detail.gallons     as detail_gallons,
    rollup.gallons     as rollup_gallons,
    detail.deliveries  as detail_deliveries,
    rollup.deliveries  as rollup_deliveries
from detail
cross join rollup
where coalesce(detail.margin, 0)     <> coalesce(rollup.margin, 0)
   or coalesce(detail.gallons, 0)    <> coalesce(rollup.gallons, 0)
   or coalesce(detail.deliveries, 0) <> coalesce(rollup.deliveries, 0)
