-- Revenue computed in the warehouse must equal what the application billed.
-- If these ever diverge, either the pipeline is wrong or the application is,
-- and both are worth stopping for. One cent of tolerance for rounding.
select
    invoices.invoice_key,
    invoices.invoice_amount,
    deliveries.revenue,
    abs(invoices.invoice_amount - deliveries.revenue) as difference
from {{ ref('fct_invoices') }} as invoices
join {{ ref('fct_deliveries') }} as deliveries
    on deliveries.delivery_key = invoices.delivery_key
where abs(invoices.invoice_amount - deliveries.revenue) > 0.01
