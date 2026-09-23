select
    customer_id     as customer_key,
    tenant_id       as tenant_key,
    customer_name,
    customer_email,
    customer_phone,
    payment_terms_days,
    case
        when payment_terms_days <= 15 then 'Net 15 or better'
        when payment_terms_days <= 30 then 'Net 30'
        else 'Net 45+'
    end             as payment_terms_band,
    customer_created_at
from {{ ref('stg_customers') }}
