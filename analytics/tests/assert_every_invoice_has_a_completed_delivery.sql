-- Billing for a delivery that never completed is the worst failure this
-- system could have: the customer is charged for fuel they did not receive.
select
    invoices.invoice_key,
    invoices.invoice_number,
    deliveries.delivery_status
from {{ ref('fct_invoices') }} as invoices
join {{ ref('fct_deliveries') }} as deliveries
    on deliveries.delivery_key = invoices.delivery_key
where deliveries.delivery_status <> 'completed'
