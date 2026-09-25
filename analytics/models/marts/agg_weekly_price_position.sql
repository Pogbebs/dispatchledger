{{
    config(
        materialized='table',
        post_hook=[
            "grant usage on schema {{ this.schema }} to dispatch_app",
            "grant select on {{ this }} to dispatch_app",
            "alter table {{ this }} enable row level security",
            "drop policy if exists tenant_isolation on {{ this }}",
            "create policy tenant_isolation on {{ this }} using (tenant_key = nullif(current_setting('app.current_tenant', true), '')::uuid)",
        ]
    )
}}

/*
  Grain: one row per tenant per delivery week.

  This is the only warehouse model the application reads directly, which is
  why it is the only one carrying a row-security policy. The five hooks above
  are the whole reason it can be exposed safely, and each is doing something:

    - The API connects as dispatch_app, which owns nothing in this schema, so
      it needs USAGE on the schema and SELECT on the table before it can read
      a single row. Without both, the policy below would never even be
      reached.

    - The policy is re-created on every run because a table-materialized model
      is DROPped and rebuilt each time dbt runs. A policy is a property of the
      table, not of the data in it, so it dies with the old table. Attaching
      it as a post-hook is what makes the protection survive a rebuild --
      getting this wrong means isolation silently disappears the first night
      the pipeline runs.

    - ENABLE, not FORCE, is deliberate. Table owners are exempt from their own
      policies unless forced, and the owner here is dispatch_analytics, which
      holds BYPASSRLS anyway. dbt's own tests query as that role and must see
      every tenant to check the rollup reconciles. The protection is aimed at
      dispatch_app, which is neither the owner nor a superuser -- exactly the
      condition under which Postgres enforces a policy.

  Only rows with a market price are aggregated. Non-diesel deliveries have no
  EIA benchmark and carry a null price upstream; averaging them in would drag
  the tenant's price toward products the benchmark says nothing about.
*/

with benchmark as (

    select * from {{ ref('fct_price_benchmark') }}
    where is_benchmarked
      and market_price is not null

)

select
    tenant_key,
    date_trunc('week', delivered_date_key)::date              as week_start,

    count(*)                                                  as delivery_count,
    sum(delivered_gal)                                        as delivered_gal,
    sum(revenue)                                              as revenue,
    sum(benchmark_revenue)                                    as benchmark_revenue,
    sum(margin_vs_benchmark)                                  as margin_vs_benchmark,

    /*
      Volume-weighted, not an average of the per-delivery prices. A 20,000
      gallon load and a 200 gallon top-up are one row each, so a plain
      avg(agreed_unit_price) would let the small delivery move the weekly
      figure as much as the large one. Dividing summed revenue by summed
      gallons gives the price the tenant actually realised that week.
    */
    round(sum(revenue) / nullif(sum(delivered_gal), 0), 4)    as avg_price,

    -- The same weighting applied to the benchmark, so the two lines on the
    -- chart are computed the same way and their difference is meaningful.
    round(
        sum(benchmark_revenue) / nullif(sum(delivered_gal), 0), 4
    )                                                         as market_price,

    round(
        (sum(revenue) - sum(benchmark_revenue))
        / nullif(sum(delivered_gal), 0), 4
    )                                                         as price_delta

from benchmark
group by tenant_key, date_trunc('week', delivered_date_key)::date
