select
    user_id     as driver_key,
    tenant_id   as tenant_key,
    user_name   as driver_name
from {{ ref('stg_users') }}
where user_role = 'driver'
