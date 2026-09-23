with lifecycle as (
    select * from {{ ref('int_order_lifecycle') }}
    where delivery_id is not null
)

/*
  Grain: one row per delivery, scheduled or completed.

  The measures worth having here are the ones that only exist because ordered
  and delivered quantities are stored separately: shortfall and fill rate.
  A system that overwrote the ordered amount with the delivered amount could
  not compute either, and fill rate is the number an operations team actually
  manages.
*/
select
    delivery_id                                             as delivery_key,
    order_id                                                as order_key,
    tenant_id                                               as tenant_key,
    customer_id                                             as customer_key,
    site_id                                                 as site_key,
    product_id                                              as product_key,
    driver_id                                               as driver_key,
    scheduled_at::date                                      as scheduled_date_key,
    delivered_at::date                                      as delivered_date_key,

    delivery_status,
    scheduled_at,
    delivered_at,

    ordered_gal,
    delivered_gal,
    agreed_unit_price,

    -- Positive means the truck left short, which is the normal direction.
    case
        when delivered_gal is not null then ordered_gal - delivered_gal
    end                                                     as shortfall_gal,

    case
        when delivered_gal is not null and ordered_gal > 0
        then round(delivered_gal / ordered_gal, 4)
    end                                                     as fill_rate,

    case
        when delivered_gal is not null
        then round(delivered_gal * agreed_unit_price, 2)
    end                                                     as revenue,

    case
        when delivered_at is not null
        then round(extract(epoch from (delivered_at - scheduled_at)) / 3600.0, 2)
    end                                                     as hours_late,

    case
        when delivered_at is null then null
        -- Within the scheduled day counts as on time: a fuel delivery
        -- window is a day, not a minute.
        else delivered_at::date <= scheduled_at::date
    end                                                     as is_on_time,

    delivery_status = 'completed'                           as is_completed

from lifecycle
