select
    id                  as site_id,
    tenant_id,
    customer_id,
    address             as site_address,
    tank_capacity_gal,
    created_at          as site_created_at
from {{ source('app', 'delivery_sites') }}
