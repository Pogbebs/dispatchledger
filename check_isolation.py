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
results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str) -> None:
    results.append((PASS if condition else FAIL, name, detail))


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

    print(f"\nTenant isolation: {name_a} vs {name_b}\n")
    for status, name, detail in results:
        print(f"  [{status}] {name:<38} {detail}")

    failures = sum(1 for status, _, _ in results if status == FAIL)
    print(f"\n{len(results) - failures}/{len(results)} checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
