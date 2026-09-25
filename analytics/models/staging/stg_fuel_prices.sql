select
    series_id,
    price_date                          as benchmark_week,
    price_usd_per_gal                   as benchmark_price,
    loaded_at
from {{ source('external', 'raw_fuel_prices') }}
