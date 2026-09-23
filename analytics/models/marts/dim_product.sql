select
    product_id      as product_key,
    tenant_id       as tenant_key,
    product_name,
    product_unit,
    list_price
from {{ ref('stg_products') }}
