with lifecycle as (
    select * from {{ ref('int_order_lifecycle') }}
    where invoice_id is not null
)

/*
  Grain: one row per invoice.

  Aged receivables are the point of this table, so the two derived columns
  that matter are days_to_pay (how long settled invoices took) and
  days_overdue (how far past due the unpaid ones are). They are deliberately
  separate: mixing them into one "days late" column makes a paid-early
  invoice and an unpaid one look comparable, and they are not.
*/
select
    invoice_id                                          as invoice_key,
    delivery_id                                         as delivery_key,
    order_id                                            as order_key,
    tenant_id                                           as tenant_key,
    customer_id                                         as customer_key,
    product_id                                          as product_key,
    issued_date                                         as issued_date_key,
    due_date                                            as due_date_key,

    invoice_number,
    invoice_status,
    invoice_amount,
    paid_at,

    invoice_status = 'paid'                             as is_paid,

    (due_date - issued_date)                            as terms_days,

    case
        when paid_at is not null then (paid_at::date - issued_date)
    end                                                 as days_to_pay,

    case
        when paid_at is not null then paid_at::date <= due_date
    end                                                 as paid_on_time,

    case
        when invoice_status = 'unpaid' and due_date < current_date
        then current_date - due_date
        else 0
    end                                                 as days_overdue,

    invoice_status = 'unpaid' and due_date < current_date as is_overdue,

    -- Standard receivables buckets, so an ageing report is a group-by
    -- rather than a pile of case statements in a BI tool.
    case
        when invoice_status <> 'unpaid' then 'Settled'
        when due_date >= current_date then 'Current'
        when current_date - due_date <= 30 then '1-30 days'
        when current_date - due_date <= 60 then '31-60 days'
        when current_date - due_date <= 90 then '61-90 days'
        else '90+ days'
    end                                                 as ageing_bucket

from lifecycle
