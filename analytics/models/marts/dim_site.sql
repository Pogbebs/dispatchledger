select
    site_id             as site_key,
    tenant_id           as tenant_key,
    customer_id         as customer_key,
    site_address,
    tank_capacity_gal,
    case
        when tank_capacity_gal <= 2000 then 'Small (<= 2k)'
        when tank_capacity_gal <= 5000 then 'Medium (2k-5k)'
        when tank_capacity_gal <= 10000 then 'Large (5k-10k)'
        else 'Bulk (10k+)'
    end                 as tank_size_band
from {{ ref('stg_sites') }}
