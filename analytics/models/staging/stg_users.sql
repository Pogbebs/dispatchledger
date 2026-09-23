select
    id          as user_id,
    tenant_id,
    full_name   as user_name,
    role        as user_role
from {{ source('app', 'users') }}
