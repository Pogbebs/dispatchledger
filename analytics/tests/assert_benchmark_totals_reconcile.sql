-- Every completed delivery must appear here exactly once. If this model ever
-- filters rows away, revenue reported from it would silently disagree with
-- fct_deliveries, and nothing else would catch it.
with counts as (
    select
        (select count(*) from {{ ref('fct_deliveries') }} where is_completed) as source_rows,
        (select count(*) from {{ ref('fct_price_benchmark') }}) as benchmark_rows
)
select * from counts where source_rows <> benchmark_rows
