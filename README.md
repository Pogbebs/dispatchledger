# DispatchLedger

[![CI](https://github.com/Pogbebs/dispatchledger/actions/workflows/ci.yml/badge.svg)](https://github.com/Pogbebs/dispatchledger/actions/workflows/ci.yml)

A multi-tenant operations platform for fuel and bulk-liquid distributors — customers, delivery sites, orders, deliveries and invoicing — with every company's data isolated inside the database itself, and a nightly pipeline turning the operational record into a tested warehouse.

Built to answer the question that defines multi-tenant SaaS: **how do you guarantee one customer can never see another's data?** The answer here is Postgres row-level security rather than a `WHERE` clause developers have to remember.

![Orders board](docs/orders-board.png)

---

## What's in it

```mermaid
flowchart LR
    U[React app<br/>orders, deliveries] --> A[FastAPI<br/>auth + tenant scoping]
    A --> P[(Postgres<br/>row-level security)]
    E[EIA open data<br/>diesel prices] --> W[Airflow<br/>daily at 06:00]
    W --> P
    W --> D[dbt<br/>star schema + 69 tests]
    P --> D
    D --> M[(Marts<br/>facts and dimensions)]
```

| Layer | What it does |
|---|---|
| **Database** | 8 tables, every schema change an Alembic migration, tenant isolation enforced by RLS policies |
| **API** | FastAPI with JWT auth, per-request tenant scoping, role-based access, 27 tests |
| **Web** | React + TypeScript: orders board, delivery completion, customer list |
| **Warehouse** | dbt star schema — 6 dimensions, 3 facts, 69 data tests |
| **Pipeline** | Airflow DAG ingesting live EIA fuel prices, rebuilding and testing the warehouse nightly |

## The core idea: isolation the application cannot forget

The usual approach filters by tenant in application code:

```python
session.query(Order).filter(Order.tenant_id == current_user.tenant_id)
```

One forgotten filter in one endpoint leaks another company's data. The filter is a convention, and conventions fail.

Here the rule lives in Postgres. Every tenant-scoped table carries a policy:

```sql
CREATE POLICY tenant_isolation ON orders
    USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
```

The API sets `app.current_tenant` once per request from the authenticated user's token. From then on, a bare `SELECT * FROM orders` returns only that tenant's rows. There is nothing to forget.

Three details make it hold up:

- **It fails closed.** `current_setting(..., true)` returns `NULL` when the tenant is unset, and `NULL = anything` is `NULL`. A request that never sets the tenant sees **zero** rows, not every row.
- **The app role is not a superuser.** Postgres lets superusers bypass row-level security entirely, so the API connects as `dispatch_app`, a plain login role that owns nothing. Testing isolation as the owner would pass while proving nothing.
- **Writes are checked too.** `WITH CHECK` on each policy means a tenant cannot insert a row belonging to someone else, not just fail to read one.

### Proving it, not claiming it

`check_isolation.py` connects as the application role and asserts the guarantee end to end:

```
Tenant isolation: Gulf Coast Fuel Co. vs Lone Star Bulk Supply

  [PASS] unset tenant sees no rows              saw 0 customers with no tenant set
  [PASS] each tenant sees a slice               Gulf Coast: 12, Lone Star: 12
  [PASS] slices sum to the full table           12 + 12 == 24
  [PASS] cross-tenant query returns nothing     returned 0
  [PASS] orders expose one tenant only          orders visible from 1 tenant(s)
  [PASS] cannot write into another tenant       insert rejected by the row-security policy

6/6 checks passed.
```

## The API

Tenant scoping happens once, in a request dependency, from the authenticated user's token:

```python
with tenant_session(user.tenant_id) as session:
    yield session
```

Handlers then query with no tenant filter at all:

```python
stmt = select(Customer).order_by(Customer.name)
return list(session.scalars(stmt))
```

`tenant_session` sets `app.current_tenant` with `SET LOCAL`, binding it to the transaction so it cannot survive on a pooled connection into the next request. A test alternates between two tenants thirty times to confirm it.

The tenant travels in the signed token, so there is no tenant parameter anywhere in the API for a client to tamper with. Requesting another tenant's record by its real id returns **404** — the policy hid the row, so the handler genuinely cannot tell it apart from one that does not exist.

Interactive docs at `/docs`. Demo credentials after seeding: tenant `gulf-coast`, user `admin@gulf-coast.example.com`, password `demo1234`. Sign in as `driver1@` instead to see the same screens with fewer permissions.

## The warehouse

dbt models the operational tables into a star schema, read by a third role:

**`dispatch_analytics` carries `BYPASSRLS`** — the deliberate exception. Analytics has to read across every tenant, which is exactly what the application role must never do, so the exception gets its own auditable credential rather than being smuggled through the app's.

That trade has a cost: with RLS bypassed, nothing at the database level stops a careless join from stitching one tenant's delivery to another tenant's customer. `assert_no_cross_tenant_rows.sql` is the replacement for the protection given up.

Two measures exist only because of a schema decision made on day one. Ordered and delivered quantities are separate columns, so `fct_deliveries` can compute **shortfall** and **fill rate** — the number an operations team actually manages. A system that overwrote ordered with delivered could compute neither.

Five of the 69 tests name a specific failure rather than checking a shape:

| Test | What it catches |
|---|---|
| `assert_every_invoice_has_a_completed_delivery` | Billing for fuel that never arrived |
| `assert_invoice_amount_matches_delivery` | Warehouse revenue diverging from what the app billed |
| `assert_no_cross_tenant_rows` | A join crossing the tenant boundary |
| `assert_benchmark_totals_reconcile` | A model silently filtering rows out of a margin report |
| `assert_fill_rate_is_plausible` | Impossible deliveries distorting every average downstream |

## The pipeline

An Airflow DAG runs daily at 06:00 UTC:

```
fetch_fuel_prices → load_fuel_prices → dbt_build → check_source_freshness
```

Each step encodes a decision:

- **The price fetch skips rather than fails** without an API key, and `dbt_build` uses `trigger_rule="none_failed"` so the warehouse still rebuilds. An optional enrichment should not fail a run — that is how alerting becomes noise people ignore.
- **The loader upserts** on `(series_id, price_date)`. EIA revises recent weeks, and a retry must not double rows. That is what makes the task idempotent and safe for Airflow to retry.
- **It runs `dbt build`, not `run` then `test`** — build interleaves each model with its tests and stops a branch when they fail, rather than building everything downstream of bad data first.
- **dbt lives in its own virtualenv** inside the Airflow image. The two pin incompatible versions of `click`; installing them together yields an environment that imports fine and misbehaves subtly.

`fct_price_benchmark` prices each diesel delivery against the national retail benchmark published that week or earlier — an as-of join, because an equality join would match almost nothing and taking the nearest week either way would price a past sale against a market that did not exist yet.

Non-diesel deliveries are kept with a null market price rather than dropped. Gasoline and DEF move on different markets, and a margin report over a silently filtered subset is the classic way these models lie.

## Data model decisions

| Decision | Why |
|---|---|
| `orders.unit_price` snapshots the price at order time | Fuel prices move daily. Pointing invoices at `products.current_price` would silently rewrite last month's billing. |
| Ordered and delivered quantities are separate columns | Trucks routinely deliver short. Invoices bill what arrived, and the gap is a real metric: fill rate. |
| Money is `NUMERIC(12,2)`, never a float | Floating point loses cents. Values stay strings all the way to the browser so display code cannot reintroduce it. |
| Statuses are constrained with `CHECK` | Keeps invalid states out of the database rather than out of the code that writes to it. |
| `users.email` is unique per tenant, not globally | The same person may work for two distributors that both use the platform. |
| UUID primary keys | Sequential integers leak volume and invite enumeration across tenant boundaries. |

![Database schema](docs/schema.png)

## Testing

| Suite | Count | What it covers |
|---|---|---|
| `check_isolation.py` | 6 | Tenant isolation at the database level, as the app role |
| `pytest` | 27 | Auth, roles, business rules, cross-tenant 404s, connection-pool leakage |
| `dbt test` | 69 | Schema constraints, referential integrity, and five named data defects |

All three run in CI against a real Postgres, along with a TypeScript build and a DAG import check.

## Running it

Requires Docker, [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
# 1. Start Postgres
docker run --name dispatch-db \
  -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=dispatch -e POSTGRES_DB=dispatchledger \
  -p 5433:5432 -d postgres:16

# 2. Install dependencies
uv sync

# 3. Build the schema, roles and row-level security policies
uv run alembic upgrade head

# 4. Load two tenants of six months of trading
uv run python seed.py

# 5. Verify tenant isolation
uv run python check_isolation.py

# 6. Run the API tests
uv run pytest -q

# 7. Start the API (docs at http://localhost:8000/docs)
uv run uvicorn dispatchledger.main:app --reload
```

The web app, in a second terminal:

```bash
cd web && npm install && npm run dev     # http://localhost:5173
```

The warehouse:

```bash
cd analytics
export DBT_PROFILES_DIR=$PWD
uv run dbt build                         # 18 models, 69 tests
```

The pipeline:

```bash
cd pipelines
cp .env.example .env                     # add a free EIA key, or leave blank
docker compose up -d --build             # Airflow at http://localhost:8081
```

Without an EIA key the price fetch skips and everything else still runs. Get one at [eia.gov/opendata](https://www.eia.gov/opendata/register.php).

Sample data is roughly 24 customers, 440 orders, 411 deliveries and 363 invoices across six months and two tenants, generated with Faker under a fixed seed so runs are reproducible.

## Stack

Python 3.14 · PostgreSQL 16 · SQLAlchemy 2.0 · Alembic · FastAPI · React 18 · TypeScript · Vite · dbt · Airflow 3 · Docker · uv

## Status

| | |
|---|---|
| Data model, row-level security, seed data, isolation checks | done |
| REST API — auth, per-request tenant scoping, role-based access | done |
| Web interface — orders board, delivery completion, customers | done |
| Warehouse — dbt star schema with 69 data tests | done |
| Pipeline — Airflow, live EIA price ingest, nightly rebuild | done |
| CI — tests, warehouse, type-check and DAG parse on every push | done |
| Cloud deployment | planned |

---

Built by [Praise Ogbebor](https://github.com/Pogbebs).
