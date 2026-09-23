-- A tank cannot take meaningfully more than was ordered, and a completed
-- delivery of nothing is a data entry error rather than a real event.
-- Either would quietly distort every fill-rate average downstream.
select
    delivery_key,
    ordered_gal,
    delivered_gal,
    fill_rate
from {{ ref('fct_deliveries') }}
where fill_rate is not null
  and (fill_rate <= 0 or fill_rate > 1.05)
