select
    id              as order_id,
    tenant_id,
    customer_id,
    site_id,
    product_id,
    quantity_gal    as ordered_gal,
    -- The price agreed when the order was placed, not today's list price.
    unit_price      as agreed_unit_price,
    status          as order_status,
    requested_date,
    created_at      as order_created_at
from {{ source('app', 'orders') }}
