with orders as (
    select * from {{ ref('stg_orders') }}
),

deliveries as (
    select * from {{ ref('stg_deliveries') }}
),

invoices as (
    select * from {{ ref('stg_invoices') }}
)

/*
  One row per order, carrying its delivery and invoice if they exist.

  Left joins, deliberately: a pending or cancelled order has no delivery, and
  a scheduled delivery has no invoice yet. Inner joins here would quietly drop
  every order that has not run its full course, which is exactly the set an
  operations team cares most about.
*/
select
    orders.order_id,
    orders.tenant_id,
    orders.customer_id,
    orders.site_id,
    orders.product_id,
    orders.ordered_gal,
    orders.agreed_unit_price,
    orders.order_status,
    orders.requested_date,

    deliveries.delivery_id,
    deliveries.driver_id,
    deliveries.scheduled_at,
    deliveries.delivered_at,
    deliveries.delivered_gal,
    deliveries.delivery_status,

    invoices.invoice_id,
    invoices.invoice_number,
    invoices.issued_date,
    invoices.due_date,
    invoices.invoice_amount,
    invoices.invoice_status,
    invoices.paid_at

from orders
left join deliveries on deliveries.order_id = orders.order_id
left join invoices on invoices.delivery_id = deliveries.delivery_id
