-- A paid invoice with no payment date makes days_to_pay silently null and
-- drags every collection-speed average toward whatever survives.
select invoice_key, invoice_number
from {{ ref('fct_invoices') }}
where is_paid and paid_at is null
