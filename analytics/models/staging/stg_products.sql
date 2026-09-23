select
    id              as product_id,
    tenant_id,
    name            as product_name,
    unit            as product_unit,
    current_price   as list_price
from {{ source('app', 'products') }}
