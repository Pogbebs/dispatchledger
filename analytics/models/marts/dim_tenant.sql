select
    tenant_id       as tenant_key,
    tenant_name,
    tenant_slug,
    tenant_created_at
from {{ ref('stg_tenants') }}
