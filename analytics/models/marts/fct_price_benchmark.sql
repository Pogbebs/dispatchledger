with deliveries as (
    select * from {{ ref('fct_deliveries') }}
    where is_completed
      and delivered_date_key is not null
),

products as (
    select product_key, product_name from {{ ref('dim_product') }}
),

benchmark as (
    select * from {{ ref('stg_fuel_prices') }}
),

/*
  The EIA series this pipeline loads is retail No 2 diesel. Gasoline and DEF
  move on different markets, so pricing them against a diesel benchmark would
  produce a number that looks meaningful and is not.

  Rows for those products are kept with a null market price rather than
  dropped: a margin report over a filtered subset silently understates volume,
  and the reader has no way to tell. Keeping every completed delivery means
  the totals here always reconcile with fct_deliveries.
*/
priced as (
    select
        deliveries.delivery_key,
        deliveries.tenant_key,
        deliveries.customer_key,
        deliveries.product_key,
        products.product_name,
        deliveries.delivered_date_key,
        deliveries.delivered_gal,
        deliveries.agreed_unit_price,
        deliveries.revenue,

        products.product_name ilike '%diesel%'          as is_benchmarked,

        -- As-of join: the most recent week published on or before the
        -- delivery. An equality join would match almost nothing, and taking
        -- the nearest week in either direction would price a past sale
        -- against a market that did not exist yet.
        case when products.product_name ilike '%diesel%' then (
            select benchmark.benchmark_price
            from benchmark
            where benchmark.benchmark_week <= deliveries.delivered_date_key
            order by benchmark.benchmark_week desc
            limit 1
        ) end                                           as market_price,

        case when products.product_name ilike '%diesel%' then (
            select benchmark.benchmark_week
            from benchmark
            where benchmark.benchmark_week <= deliveries.delivered_date_key
            order by benchmark.benchmark_week desc
            limit 1
        ) end                                           as benchmark_week

    from deliveries
    join products on products.product_key = deliveries.product_key
)

select
    delivery_key,
    tenant_key,
    customer_key,
    product_key,
    product_name,
    delivered_date_key,
    benchmark_week,
    is_benchmarked,

    delivered_gal,
    agreed_unit_price,
    market_price,
    revenue,

    -- Positive means the tenant charged above the national market.
    round(agreed_unit_price - market_price, 4)                      as price_delta,

    case
        when market_price > 0
        then round((agreed_unit_price - market_price) / market_price, 4)
    end                                                             as price_delta_pct,

    -- What the same gallons would have been worth at the market price, so
    -- margin against the benchmark can be summed rather than averaged.
    round(delivered_gal * market_price, 2)                          as benchmark_revenue,
    round(delivered_gal * (agreed_unit_price - market_price), 2)    as margin_vs_benchmark

from priced
