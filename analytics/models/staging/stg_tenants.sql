select
    id            as tenant_id,
    name          as tenant_name,
    slug          as tenant_slug,
    created_at    as tenant_created_at
from {{ source('app', 'tenants') }}
