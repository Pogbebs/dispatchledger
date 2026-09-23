select
    id                  as customer_id,
    tenant_id,
    name                as customer_name,
    email               as customer_email,
    phone               as customer_phone,
    payment_terms_days,
    created_at          as customer_created_at
from {{ source('app', 'customers') }}
