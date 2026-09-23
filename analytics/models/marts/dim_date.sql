/*
  A date spine covering every date the data touches, plus a little headroom.
  Built from the data's own range rather than hardcoded, so it never silently
  runs out at the end of a year.
*/
with bounds as (
    select
        least(min(requested_date), current_date - 400) as start_date,
        greatest(max(due_date), current_date + 120)    as end_date
    from {{ ref('int_order_lifecycle') }}
),

spine as (
    select generate_series(start_date, end_date, interval '1 day')::date as date_day
    from bounds
)

select
    date_day                                            as date_key,
    extract(year from date_day)::int                    as calendar_year,
    extract(quarter from date_day)::int                 as calendar_quarter,
    extract(month from date_day)::int                   as calendar_month,
    to_char(date_day, 'Mon')                            as month_name,
    to_char(date_day, 'YYYY-MM')                        as year_month,
    extract(day from date_day)::int                     as day_of_month,
    extract(isodow from date_day)::int                  as day_of_week,
    to_char(date_day, 'Dy')                             as day_name,
    extract(isodow from date_day) in (6, 7)             as is_weekend,
    date_trunc('week', date_day)::date                  as week_start_date,
    date_trunc('month', date_day)::date                 as month_start_date
from spine
