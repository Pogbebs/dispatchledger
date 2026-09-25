"""Prove that row-level security isolates tenants.

Connects as dispatch_app -- a plain login role, not a superuser and not the
table owner -- because Postgres lets superusers bypass RLS entirely. Running
this as `dispatch` would pass vacuously and prove nothing.
"""

import os

import psycopg

APP_URL = os.getenv(
    "APP_DATABASE_URL",
    "postgresql://dispatch_app:dispatch_app@localhost:5433/dispatchledger",
)

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
results: list[tuple[str, str, str]] = []

# The one warehouse model the application reads. dbt drops and recreates it on
# every run, so its row-security policy is re-applied as a post-hook -- which
# is exactly the kind of thing that works on the day it is written and
# silently stops working later. Hence the last two checks.
MART = "analytics_marts.agg_weekly_price_position"


def check(name: str, condition: bool, detail: str) -> None:
    results.append((PASS if condition else FAIL, name, detail))


def skip(name: str, detail: str) -> None:
    results.append((SKIP, name, detail))


def set_tenant(cur: psycopg.Cursor, tenant_id: str | None) -> None:
    """Scope the session to one tenant, the way a request handler will."""
    cur.execute("SELECT set_config('app.current_tenant', %s, false)", (tenant_id or "",))


def main() -> int:
    # Tenant ids are read with a superuser connection, since the app role
    # cannot see the tenants table without a tenant already set.
    owner_url = os.getenv(
        "DATABASE_URL_RAW",
        "postgresql://dispatch:dispatch@localhost:5433/dispatchledger",
    )
    with psycopg.connect(owner_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name FROM tenants ORDER BY name")
        tenants = cur.fetchall()
        cur.execute("SELECT count(*) FROM customers")
        total_customers = cur.fetchone()[0]

        # Read as the owner, which bypasses row security, so the per-tenant
        # slices below have a true total to be measured against.
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (MART,))
        mart_built = cur.fetchone()[0]
        mart_total = None
        if mart_built:
            cur.execute(f"SELECT count(*) FROM {MART}")  # noqa: S608 -- constant
            mart_total = cur.fetchone()[0]

    if len(tenants) < 2:
        print("Need at least two tenants. Run seed.py first.")
        return 1

    (tenant_a, name_a), (tenant_b, name_b) = tenants[0], tenants[1]

    with psycopg.connect(APP_URL) as conn, conn.cursor() as cur:
        # 1. No tenant set: the app sees nothing at all.
        set_tenant(cur, None)
        cur.execute("SELECT count(*) FROM customers")
        unset_count = cur.fetchone()[0]
        check(
            "unset tenant sees no rows",
            unset_count == 0,
            f"saw {unset_count} customers with no tenant set",
        )

        # 2. Each tenant sees only its own rows, and the parts sum to the whole.
        set_tenant(cur, str(tenant_a))
        cur.execute("SELECT count(*) FROM customers")
        count_a = cur.fetchone()[0]

        set_tenant(cur, str(tenant_b))
        cur.execute("SELECT count(*) FROM customers")
        count_b = cur.fetchone()[0]

        check(
            "each tenant sees a slice",
            count_a > 0 and count_b > 0,
            f"{name_a}: {count_a}, {name_b}: {count_b}",
        )
        check(
            "slices sum to the full table",
            count_a + count_b == total_customers,
            f"{count_a} + {count_b} == {total_customers}",
        )

        # 3. A deliberate cross-tenant query returns nothing.
        set_tenant(cur, str(tenant_a))
        cur.execute("SELECT count(*) FROM customers WHERE tenant_id = %s", (tenant_b,))
        leaked = cur.fetchone()[0]
        check(
            "cross-tenant query returns nothing",
            leaked == 0,
            f"asking for {name_b}'s rows while scoped to {name_a} returned {leaked}",
        )

        # 4. Orders are isolated too, not just the table we happened to test.
        set_tenant(cur, str(tenant_a))
        cur.execute("SELECT count(DISTINCT tenant_id) FROM orders")
        distinct_tenants = cur.fetchone()[0]
        check(
            "orders expose one tenant only",
            distinct_tenants == 1,
            f"orders visible from {distinct_tenants} tenant(s)",
        )

        # 5. Writing a row for another tenant is rejected by WITH CHECK.
        set_tenant(cur, str(tenant_a))
        try:
            cur.execute(
                "INSERT INTO customers (tenant_id, name) VALUES (%s, %s)",
                (tenant_b, "Smuggled Row"),
            )
            conn.rollback()
            check("cannot write into another tenant", False, "the insert was allowed")
        except (psycopg.errors.InsufficientPrivilege, psycopg.errors.CheckViolation):
            conn.rollback()
            check(
                "cannot write into another tenant",
                True,
                "insert rejected by the row-security policy",
            )

        # 6. The warehouse mart the API reads is isolated too.
        #
        # This is the check most likely to catch a real regression. Every
        # table above is created once by a migration and keeps its policy
        # forever. The mart is dropped and rebuilt by dbt every night, so its
        # policy only exists because a post-hook re-creates it. Forget that
        # hook and this is the only thing standing between one distributor
        # and another's pricing.
        #
        # An empty mart is skipped rather than failed. Without an EIA key
        # there are no benchmark prices, so the model builds to zero rows --
        # and "how many tenants can I see" has no meaningful answer over an
        # empty table. Failing there would mean a green key is required to get
        # a green build, which is how a check ends up being disabled.
        if not mart_built:
            skip(
                "warehouse mart is tenant-scoped",
                "run `dbt build` in analytics/ to include this check",
            )
            skip("mart slices sum to the whole", "warehouse not built")
        elif not mart_total:
            skip("warehouse mart is tenant-scoped", "mart is empty (no EIA prices loaded)")
            skip("mart slices sum to the whole", "mart is empty")
        else:
            set_tenant(cur, str(tenant_a))
            cur.execute(f"SELECT count(DISTINCT tenant_key) FROM {MART}")  # noqa: S608
            mart_tenants = cur.fetchone()[0]
            cur.execute(f"SELECT count(*) FROM {MART}")  # noqa: S608
            mart_a = cur.fetchone()[0]

            set_tenant(cur, str(tenant_b))
            cur.execute(f"SELECT count(*) FROM {MART}")  # noqa: S608
            mart_b = cur.fetchone()[0]

            check(
                "warehouse mart is tenant-scoped",
                mart_tenants == 1,
                f"weekly rows visible from {mart_tenants} tenant(s)",
            )
            check(
                "mart slices sum to the whole",
                mart_a + mart_b == mart_total,
                f"{mart_a} + {mart_b} == {mart_total} weekly rows",
            )

    print(f"\nTenant isolation: {name_a} vs {name_b}\n")
    for status, name, detail in results:
        print(f"  [{status}] {name:<38} {detail}")

    failures = sum(1 for status, _, _ in results if status == FAIL)
    skipped = sum(1 for status, _, _ in results if status == SKIP)
    ran = len(results) - skipped

    tail = f" ({skipped} skipped: warehouse not built)" if skipped else ""
    print(f"\n{ran - failures}/{ran} checks passed{tail}.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
