select
    id              as delivery_id,
    tenant_id,
    order_id,
    driver_id,
    scheduled_at,
    delivered_at,
    delivered_gal,
    status          as delivery_status
from {{ source('app', 'deliveries') }}
