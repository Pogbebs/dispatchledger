# DispatchLedger

A multi-tenant operations platform for fuel and bulk-liquid distributors: customers, delivery sites, orders, deliveries and invoicing, with every company's data isolated inside the database itself.

Built to explore the problem that defines multi-tenant SaaS — **how do you guarantee one customer can never see another's data?** — and to answer it with Postgres row-level security rather than a `WHERE` clause developers have to remember.

![Database schema](docs/schema.png)

---

## The core idea: isolation the application cannot forget

The usual approach is to filter by tenant in application code:

```python
session.query(Order).filter(Order.tenant_id == current_user.tenant_id)
```

One forgotten filter in one endpoint leaks another company's data. The filter is a convention, and conventions fail.

Here the rule lives in Postgres. Every tenant-scoped table carries a policy:

```sql
CREATE POLICY tenant_isolation ON orders
    USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
```

The API sets `app.current_tenant` once per request, from the authenticated user's token. From then on, a bare `SELECT * FROM orders` returns only that tenant's rows. There is nothing to forget.

Three details make it hold up:

- **It fails closed.** `current_setting(..., true)` returns `NULL` when the tenant is unset, and `NULL = anything` is `NULL`. A request that never sets the tenant sees **zero** rows, not every row.
- **The app role is not a superuser.** Postgres lets superusers bypass row-level security entirely, so the API connects as `dispatch_app`, a plain login role that owns nothing. Testing isolation as the owner would pass while proving nothing.
- **Writes are checked too.** `WITH CHECK` on each policy means a tenant cannot insert a row belonging to someone else, not just fail to read one.

## Proving it, not claiming it

`check_isolation.py` connects as the application role and asserts the guarantee end to end:

```
Tenant isolation: Gulf Coast Fuel Co. vs Lone Star Bulk Supply

  [PASS] unset tenant sees no rows              saw 0 customers with no tenant set
  [PASS] each tenant sees a slice               Gulf Coast Fuel Co.: 12, Lone Star Bulk Supply: 12
  [PASS] slices sum to the full table           12 + 12 == 24
  [PASS] cross-tenant query returns nothing     asking for Lone Star's rows while scoped to Gulf Coast returned 0
  [PASS] orders expose one tenant only          orders visible from 1 tenant(s)
  [PASS] cannot write into another tenant       insert rejected by the row-security policy

6/6 checks passed.
```

## Data model decisions

| Decision | Why |
|---|---|
| `orders.unit_price` snapshots the price at order time | Fuel prices move daily. Pointing invoices at `products.current_price` would silently rewrite last month's billing. |
| Ordered quantity and delivered quantity are separate columns | Trucks routinely deliver short. Invoices bill what was delivered, and the gap between the two becomes a real operational metric: fill rate. |
| Money is `NUMERIC(12,2)`, never a float | Floating point loses cents. |
| Statuses are constrained to fixed values | `CHECK (status IN (...))` keeps invalid states out of the database rather than out of the code that writes to it. |
| `users.email` is unique per tenant, not globally | The same person may work for two distributors that both use the platform. |
| UUID primary keys | Sequential integers leak volume and invite enumeration across tenant boundaries. |

## Schema as code

Every schema change is an Alembic migration committed to this repository, so the database has a version history and anyone can rebuild it identically:

```
migrations/versions/
  f669781c19e5_initial_schema.py     # eight tables, keys, constraints, indexes
  369c0108e8fd_row_level_security.py # app role, policies, grants
```

## Running it

Requires Docker and [uv](https://docs.astral.sh/uv/).

```bash
# 1. Start Postgres
docker run --name dispatch-db \
  -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=dispatch -e POSTGRES_DB=dispatchledger \
  -p 5433:5432 -d postgres:16

# 2. Install dependencies
uv sync

# 3. Build the schema and apply row-level security
uv run alembic upgrade head

# 4. Load two tenants of realistic sample data
uv run python seed.py

# 5. Verify tenant isolation
uv run python check_isolation.py
```

Sample data is roughly 24 customers, 440 orders, 411 deliveries and 363 invoices across six months and two tenants, generated with Faker under a fixed seed so runs are reproducible.

## Stack

Python 3.14 · PostgreSQL 16 · SQLAlchemy 2.0 · Alembic · Docker · uv

## Status

| | |
|---|---|
| Data model, row-level security, seed data, isolation checks | done |
| REST API — authentication, tenant scoping per request, role-based access | in progress |
| Web interface — orders board, delivery tracking, invoicing | planned |
| Analytics pipeline — Airflow and dbt into a tested dimensional model | planned |
| CI/CD and cloud deployment | planned |

---

Built by [Praise Ogbebor](https://github.com/Pogbebs).
