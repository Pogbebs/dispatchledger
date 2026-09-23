-- The analytics role bypasses row-level security by design, so nothing at
-- the database level stops a careless join from stitching one tenant's
-- delivery to another tenant's customer. This test is the replacement for
-- the protection that BYPASSRLS gives up.
select
    deliveries.delivery_key,
    deliveries.tenant_key      as delivery_tenant,
    customers.tenant_key       as customer_tenant,
    products.tenant_key        as product_tenant
from {{ ref('fct_deliveries') }} as deliveries
join {{ ref('dim_customer') }} as customers
    on customers.customer_key = deliveries.customer_key
join {{ ref('dim_product') }} as products
    on products.product_key = deliveries.product_key
where deliveries.tenant_key <> customers.tenant_key
   or deliveries.tenant_key <> products.tenant_key
