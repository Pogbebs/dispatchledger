# DispatchLedger

[![CI](https://github.com/Pogbebs/dispatchledger/actions/workflows/ci.yml/badge.svg)](https://github.com/Pogbebs/dispatchledger/actions/workflows/ci.yml)

Dispatchledger is multi-tenant data and operations platform for fuel and bulk-liquid distributors. it allows each companies its fuel orders, delivery locations, customers, and invoicing  in one system, while a nightly data pipeline transforms operational data into a tested analytics warehouse for reporting and business intelligence.

Dispatchjledger is designed as a multi-tenant SaaS application, meaning multiple companies can use the same system while their data remains securely separated. Instead of relying on developers to remember to filter every query by company, it enforces a boundary inside the PostgreSQL database using Row-Level Security (RLS),rather than relying solely on application-level WHERE tenant_id = ... filters.


### Live demo

**[dispatchledger-59zi.onrender.com](https://dispatchledger-59zi.onrender.com)**

| Sign in as | Password | You are |
|---|---|---|
| `admin@gulf-coast.example.com` | `demo1234` | Staff at Gulf Coast Fuel Co. |
| `admin@lone-star.example.com` | `demo1234` | Staff at a competing distributor |
| `customer@gulf-coast.example.com` | `demo1234` | A customer **of** Gulf Coast |

Each distributor also has `dispatch@…` and `driver1@…` accounts on the same password, if you want to see the same screens with fewer permissions.

Those three logins are worth walking in order, because each one narrows the view:

1. **The two distributors.** Same application, same queries, two disjoint sets of customers, orders and invoices. Nothing in the API filters by tenant — the policies do.
2. **The customer.** Signs into the same deployment and sees their own orders and invoices — not their distributor's other eleven customers. That is a narrower rule than tenant isolation, and it runs on a third database role whose policy is *restrictive*: ANDed with the tenant policy, so it can only ever see less, never more.

Ask the customer account for something it should not have. Type `/insights` into the address bar and you land back on your own orders; the margin data it would show sits in a schema that role has no grant on at all.

Hosted on Render's free tier, which suspends an idle service. The first request after a quiet spell takes about 50 seconds to wake; everything after that is immediate.

![Orders board](docs/orders-board.png)

---

## What's in it

```mermaid
flowchart LR
    U[React app<br/>orders, deliveries, insights] --> A[FastAPI<br/>auth + tenant scoping]
    A --> P[(Postgres<br/>row-level security)]
    E[EIA open data<br/>diesel prices] --> W[Nightly job<br/>Airflow locally]
    W --> P
    W --> D[dbt<br/>star schema + 76 tests]
    P --> D
    D --> M[(Marts<br/>facts and dimensions)]
    M -.->|RLS re-applied<br/>on every rebuild| A
```

| Layer | What it does |
|---|---|
| **Database** | 9 tables, every schema change an Alembic migration, isolation enforced by RLS policies — tenant-wide for staff, customer-scoped for the portal |
| **API** | FastAPI with JWT auth, per-request tenant scoping, role-based access, 96 tests |
| **Web** | React + TypeScript: staff platform (orders, scheduling, deliveries, customers, receivables, insights) and a customer portal |
| **Warehouse** | dbt star schema — 6 dimensions, 3 facts, 1 aggregate, 76 data tests |
| **Pipeline** | Live EIA price ingest and a nightly warehouse rebuild — Airflow locally, a scheduled workflow in production |

The dotted line is the part worth reading the code for: the application reads
one warehouse table directly, under the same row-level security as everything
else, without ever holding the analytics credential.

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
  [PASS] each tenant sees a slice               Gulf Coast Fuel Co.: 13, Lone Star Bulk Supply: 12
  [PASS] slices sum to the full table           13 + 12 == 25
  [PASS] cross-tenant query returns nothing     asking for Lone Star Bulk Supply's rows while scoped to Gulf Coast Fuel Co. returned 0
  [PASS] orders expose one tenant only          orders visible from 1 tenant(s)
  [PASS] cannot write into another tenant       insert rejected by the row-security policy
  [PASS] warehouse mart is tenant-scoped        weekly rows visible from 1 tenant(s)
  [PASS] mart slices sum to the whole           25 + 26 == 51 weekly rows

8/8 checks passed.
```

The last two are the ones most likely to catch a real regression. Every table
above them is created once by a migration and keeps its policy forever. The
mart is dropped and rebuilt by dbt every night, so its policy exists only
because a post-hook re-creates it.

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

### The screens

Completing a delivery records what actually arrived, then invoices for that amount rather than for what was ordered. Trucks routinely deliver short, so the two quantities are stored separately — and the gap between them is where fill rate comes from.

![Deliveries board](docs/Deliveries-board.png)

Customers carry the payment terms that set each invoice's due date, which is what drives the receivables ageing in the warehouse.

![Customers](docs/customer-board.png)

### The order lifecycle, end to end

A dispatcher can follow one order all the way through without leaving the app:

```
New order  ->  Schedule  ->  Complete  ->  Invoice
  (pending)    (assign a     (record      (raised for
               driver and    gallons      the gallons
               a date)       delivered)   that arrived)
```

Two details in that chain are enforced rather than assumed. A delivery can
only be assigned to a user whose role is `driver` in the same tenant — the
schema cannot express that, since `driver_id` is just a user id, so the
handler checks it and the row-security policy makes another tenant's driver
invisible rather than merely forbidden. And a completed delivery cannot be
rescheduled: its invoice is already written, and moving it afterwards would
put the billing record and the delivery record into disagreement.

Customers can be added mid-order. A first delivery to a new customer is
exactly when an order gets typed in, so requiring the customer to exist
beforehand gets the sequence backwards.

## The customer portal: a rule narrower than the tenant

Staff see everything belonging to their distributor. A customer must see
strictly less — their own orders, sites and invoices, not their distributor's
other customers'. Those rows sit in the same tables, carry the same
`tenant_id`, and differ only in `customer_id`.

The tempting fix is to widen the existing policy: match the tenant, and also
the customer *if* a customer setting is present. That inverts the design.
Every policy here fails closed, and one that read "no customer set" as "all
customers" would fail open — a missed `SET LOCAL` would hand someone their
competitor's pricing.

So the portal gets a login role of its own, and a policy that can only
subtract:

```sql
create policy customer_scope on orders
    as restrictive for all to dispatch_portal
    using (customer_id = nullif(current_setting('app.current_customer', true), '')::uuid);
```

Three words carry it. **`restrictive`** means ANDed with the tenant policy
rather than ORed: both must pass, so this connection can never see more than
a staff connection, only less. **`to dispatch_portal`** scopes it to that role
alone, so nothing staff do changes and no existing test changed. And
**`nullif(...)`** is NULL when unset, matching no row — the same failure
direction as the tenant policy.

Because the database decides, no handler in the portal filters by customer.
There is not one `where customer_id =` in the file, and adding one would be
redundant rather than protective.

| Role | Connects as | Sees |
|---|---|---|
| Staff | `dispatch_app` | Everything in their tenant |
| Customer | `dispatch_portal` | Their own rows inside that tenant |
| dbt | `dispatch_analytics` | Every tenant — `BYPASSRLS`, never on the request path |

### Accounts are issued, not claimed

There is no customer sign-up form, deliberately. Open signup would let anyone
insert themselves into a distributor's customer book, which is the boundary
this project exists to defend. The dispatcher issues a single-use invitation
from the Customers page; the customer follows the link and sets a password.
Only the token's hash is stored, so a copy of that table is not a set of
working invitations.

### The hole a fourth role opened

Adding the portal exposed a real bug in code that had been correct until then.
Several staff read endpoints — `/orders`, `/deliveries`, `/customers` — carry
no role guard, because before this there was nothing to guard against. A
customer's token would have passed straight through them on the staff
connection and listed the entire tenant.

The refusal now lives in the shared session dependency rather than on each
route, where a new endpoint cannot forget it. Six tests walk the list.

## The warehouse

dbt models the operational tables into a star schema, read by a third role:

**`dispatch_analytics` carries `BYPASSRLS`** — the deliberate exception. Analytics has to read across every tenant, which is exactly what the application role must never do, so the exception gets its own auditable credential rather than being smuggled through the app's.

That trade has a cost: with RLS bypassed, nothing at the database level stops a careless join from stitching one tenant's delivery to another tenant's customer. `assert_no_cross_tenant_rows.sql` is the replacement for the protection given up.

Two measures exist only because of a schema decision made on day one. Ordered and delivered quantities are separate columns, so `fct_deliveries` can compute **shortfall** and **fill rate** — the number an operations team actually manages. A system that overwrote ordered with delivered could compute neither.

Six of the 76 tests name a specific failure rather than checking a shape:

| Test | What it catches |
|---|---|
| `assert_every_invoice_has_a_completed_delivery` | Billing for fuel that never arrived |
| `assert_invoice_amount_matches_delivery` | Warehouse revenue diverging from what the app billed |
| `assert_no_cross_tenant_rows` | A join crossing the tenant boundary |
| `assert_benchmark_totals_reconcile` | A model silently filtering rows out of a margin report |
| `assert_fill_rate_is_plausible` | Impossible deliveries distorting every average downstream |
| `assert_weekly_position_reconciles` | A rollup drifting from the detail the user can check it against |

## Letting the app read the warehouse

The Insights screen draws one dbt model, `agg_weekly_price_position` — weekly
realised price against the national benchmark. Getting a warehouse table onto
an application screen is where the isolation guarantee usually quietly dies,
because the obvious route is to hand the API the analytics credential.

This does the opposite. The mart carries its own policy, applied as a dbt
post-hook, and the API reads it as `dispatch_app` exactly like every other
table:

```sql
{{ config(post_hook=[
    "grant usage on schema {{ this.schema }} to dispatch_app",
    "grant select on {{ this }} to dispatch_app",
    "alter table {{ this }} enable row level security",
    "create policy tenant_isolation on {{ this }} using (...)",
]) }}
```

The post-hook is not decoration. A table-materialized model is **dropped and
recreated** on every run, and a policy is a property of the table, not of the
data in it — so it dies with the old table. Attach it once by hand and
isolation disappears the first night the pipeline runs, silently, with every
test still green. That is what the two new checks in `check_isolation.py`
exist to catch.

`ENABLE` rather than `FORCE` is also deliberate: owners are exempt from their
own policies unless forced, and dbt's tests run as the owner and need to see
every tenant to verify the rollup reconciles.

Both price series on that screen are volume-weighted in the warehouse rather
than averaged per delivery. A 20,000 gallon load and a 200 gallon top-up are
one row each, so an unweighted average would let the small delivery move the
weekly figure as much as the large one — and the gap between the two lines,
which is the entire point of the chart, would be visually persuasive and
arithmetically meaningless.

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
| `check_isolation.py` | 8 | Tenant isolation at the database level, as the app role — including a dbt-rebuilt mart |
| `pytest` | 68 | Auth, roles, scheduling, receivables, cross-tenant 404s, connection-pool leakage, health |
| `dbt test` | 76 | Schema constraints, referential integrity, and six named data defects |

All three run in CI against a real Postgres, along with a TypeScript build and a DAG import check.

## Running it

Requires Docker, [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
# 1. Start Postgres
docker run --name dispatch-db \
  -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=dispatch -e POSTGRES_DB=dispatchledger \
  -p 5433:5432 -d postgres:16

# 2. Install dependencies and settings
uv sync
cp .env.example .env                     # JWT_SECRET has no default, by design

# 3. Build the schema, roles and row-level security policies
uv run alembic upgrade head

# 4. Load two tenants of six months of trading
#    Seeds against whatever EIA prices are already loaded, so running the
#    pipeline first gives demo data priced at a believable spread over the
#    real market. Without it, fixed list prices are used instead.
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
uv run dbt build                         # 20 models, 76 tests
```

The pipeline:

```bash
cd pipelines
cp .env.example .env                     # add a free EIA key, or leave blank
docker compose up -d --build             # Airflow at http://localhost:8081
```

Without an EIA key the price fetch skips and everything else still runs. Get one at [eia.gov/opendata](https://www.eia.gov/opendata/register.php).

Sample data is 25 customers, 42 delivery sites, 444 orders, 413 deliveries and 367 invoices across six months and two tenants, generated with Faker under a fixed seed so runs are reproducible.

Order prices are derived from the EIA series rather than a constant, each order taking the market as it stood on its own requested date plus a per-tenant margin — Gulf Coast around 28¢ a gallon, Lone Star around 37¢. This started as a bug worth keeping in mind: the seed originally hard-coded diesel at $3.84, which was reasonable when written and badly wrong a year later against a market that had nearly doubled. Every test still passed, because every number in the warehouse remained internally consistent. Only comparing against the outside world showed it, which is the one thing a test suite cannot do for you.

## Configuration

Nothing in this repository is a working credential. Three settings have no
usable default, and the code refuses to start rather than substituting one.

| Variable | Required | What it is |
|---|---|---|
| `JWT_SECRET` | always | Signs the tokens that carry tenant identity |
| `DATABASE_URL` | deployment | Owner role — migrations, seeding, login |
| `APP_DATABASE_URL` | deployment | `dispatch_app`, the role RLS applies to |
| `APP_DB_PASSWORD` | deployment | Password the migrations set on `dispatch_app` |
| `ANALYTICS_DB_PASSWORD` | deployment | Password for `dispatch_analytics` |
| `PORTAL_DATABASE_URL` | deployment | `dispatch_portal`, the customer-scoped role |
| `PORTAL_DB_PASSWORD` | deployment | Password the migrations set on `dispatch_portal` |
| `EIA_API_KEY` | optional | Without it the price fetch skips and everything else runs |

`JWT_SECRET` is the one that matters most, and the reason it has no fallback
is worth stating plainly: the tenant travels inside the signed token, so
anyone who knows the signing key can mint a token for any tenant and read that
company's data. A default that works would hand that to whoever reads this
repository — silently, on a deployment that looked perfectly healthy.

`ANALYTICS_DB_PASSWORD` is the second: that role carries `BYPASSRLS`, so every
policy protecting every other role is void for it.

The portal pair has to be set *before* the migration that creates the role
runs, because that migration reads `PORTAL_DB_PASSWORD` to set it. Set late,
the role is created with the development literal in this repository — on a
login reachable from the internet, by people outside the distributor. The
health check tries all three connections, so a mismatch between the two fails
the deploy instead of waiting to be discovered.

The same reasoning runs through the rest of the project. An unset tenant
returns zero rows rather than every row; an absent EIA key raises rather than
inventing a price. A default that works is more dangerous than one that does
not, because nothing tells you it is wrong.

## Stack

Python 3.14 · PostgreSQL 16 · SQLAlchemy 2.0 · Alembic · FastAPI · React 18 · TypeScript · Vite · dbt · Airflow 3 · Docker · uv

## Status

| | |
|---|---|
| Data model, row-level security, seed data, isolation checks | done |
| REST API — auth, per-request tenant scoping, role-based access | done |
| Web interface — orders board, delivery completion, customers | done |
| Order lifecycle — scheduling, reassignment, receivables | done |
| Insights — warehouse-backed pricing screen, RLS preserved across rebuilds | done |
| Warehouse — dbt star schema with 76 data tests | done |
| Pipeline — live EIA price ingest and nightly rebuild, on a schedule | done |
| CI — tests, warehouse, type-check and DAG parse on every push | done |
| Cloud deployment — Neon, Render, container build | done |
| Customer portal — restrictive policy on a third role, invitations | done |

---

Built by [Praise Ogbebor](https://github.com/Pogbebs).
