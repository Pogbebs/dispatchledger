select
    id                  as invoice_id,
    tenant_id,
    customer_id,
    delivery_id,
    invoice_number,
    issued_at           as issued_date,
    due_date,
    amount              as invoice_amount,
    status              as invoice_status,
    paid_at
from {{ source('app', 'invoices') }}
