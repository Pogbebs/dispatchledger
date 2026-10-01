"""Re-create dispatch_app and dispatch_analytics, and write their URLs.

The two login roles were dropped from the Neon database. Everything else
survived: the tables, their rows, the row-level security policies and the
analytics schema. A policy is a property of a table, not of a role, so the
isolation rules were never at risk -- but with no role to connect as, the
application cannot reach them.

This re-runs what migrations 369c0108e8fd and 1d875ec9184d do about roles:
create each one with a fresh password, then re-grant what it needs. It does
not touch the schema, so it is safe to run against a database with data in it,
and safe to run twice.

    uv run python repair_roles.py owner_url.txt

Writes app_url.txt and analytics_url.txt. Both hold live credentials; delete
them once the values are in Render.
"""

import secrets
import sys
import urllib.parse

import psycopg
from psycopg import sql


def first_line(path: str) -> str:
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        print(f"\nNo such file: {path}")
        raise SystemExit(1) from None
    for line in lines:
        line = line.strip().strip('"').strip("'")
        if line and not line.startswith("#"):
            return line
    print(f"\n{path} is empty.")
    raise SystemExit(1)


def pooled(host: str) -> str:
    """Neon's pooled endpoint: -pooler on the first label of the hostname.

    Transaction-mode pooling is why the tenant is carried with SET LOCAL --
    the setting dies with the transaction, so a connection handed back to the
    pool cannot leak one tenant's identity into the next request.
    """
    if "-pooler" in host:
        return host
    head, _, tail = host.partition(".")
    return f"{head}-pooler.{tail}" if tail else host


def ensure_role(cur, name: str, password: str, bypassrls: bool) -> None:
    """Create the role, or reset its password if it is already there.

    The migration does this with a DO block because Alembic hands Postgres a
    string. Here the existence check happens in Python and psycopg composes the
    statement, which avoids nesting a quoted password inside a quoted format
    string -- a place where an unlucky character in a generated password would
    otherwise end the statement early.
    """
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
    verb = "ALTER" if cur.fetchone() else "CREATE"

    statement = sql.SQL("{verb} ROLE {role} LOGIN PASSWORD {password}").format(
        verb=sql.SQL(verb),
        role=sql.Identifier(name),
        password=sql.Literal(password),
    )
    if bypassrls:
        statement = statement + sql.SQL(" BYPASSRLS")

    cur.execute(statement)
    print("    created" if verb == "CREATE" else "    already existed, password reset")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    owner = first_line(sys.argv[1])
    plain = owner.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urllib.parse.urlparse(plain)
    database = parsed.path.lstrip("/")

    print(f"\n  host      {parsed.hostname}")
    print(f"  database  {database}")
    print(f"  as        {parsed.username}")

    app_pw = secrets.token_urlsafe(24)
    analytics_pw = secrets.token_urlsafe(24)

    try:
        conn = psycopg.connect(plain, connect_timeout=20, autocommit=True)
    except psycopg.OperationalError as exc:
        print(f"\n  FAILED   {str(exc).strip().splitlines()[0]}")
        return 1

    with conn, conn.cursor() as cur:
        # ---- the application role: restricted on purpose ----
        # Not a superuser and not the table owner, because Postgres lets both
        # bypass row-level security. The whole design depends on this role
        # being ordinary.
        print("\n  dispatch_app")
        ensure_role(cur, "dispatch_app", app_pw, bypassrls=False)
        cur.execute("GRANT USAGE ON SCHEMA public TO dispatch_app")
        cur.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
            "IN SCHEMA public TO dispatch_app"
        )
        cur.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dispatch_app"
        )
        cur.execute(
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO dispatch_app"
        )
        print("    created, granted on public")

        # The Insights page reads one dbt mart directly. Those grants were
        # attached to the role, so they went with it.
        # The Insights page reads one dbt mart directly, and those grants were
        # attached to the role, so they went with it.
        #
        # Not just 'analytics': dbt_project.yml appends a suffix per layer, so
        # the models land in analytics_staging, analytics_intermediate and
        # analytics_marts. Granting on the bare schema alone leaves Insights
        # returning 500 -- which is exactly what it did the first time this ran.
        cur.execute(
            "SELECT nspname FROM pg_namespace "
            "WHERE nspname = 'analytics' OR nspname LIKE 'analytics\\_%' "
            "ORDER BY nspname"
        )
        for (schema,) in cur.fetchall():
            cur.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO dispatch_app").format(
                    sql.Identifier(schema)
                )
            )
            cur.execute(
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO dispatch_app").format(
                    sql.Identifier(schema)
                )
            )
            cur.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA {} "
                    "GRANT SELECT ON TABLES TO dispatch_app"
                ).format(sql.Identifier(schema))
            )
            print(f"    granted select on {schema}")

        # ---- the analytics role: the deliberate exception ----
        # BYPASSRLS, because dbt builds marts that span every tenant. One role,
        # named, auditable, and never used by the request path.
        print("\n  dispatch_analytics")
        ensure_role(cur, "dispatch_analytics", analytics_pw, bypassrls=True)
        cur.execute("GRANT USAGE ON SCHEMA public TO dispatch_analytics")
        cur.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO dispatch_analytics")
        cur.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "GRANT SELECT ON TABLES TO dispatch_analytics"
        )
        cur.execute(
            sql.SQL("GRANT CREATE ON DATABASE {} TO dispatch_analytics").format(
                sql.Identifier(database)
            )
        )
        cur.execute("GRANT CREATE, USAGE ON SCHEMA analytics TO dispatch_analytics")
        print("    created, granted on public and analytics")

        # ---- prove it took ----
        cur.execute(
            "SELECT rolname, rolbypassrls FROM pg_roles "
            "WHERE rolname IN ('dispatch_app', 'dispatch_analytics') ORDER BY 1"
        )
        rows = cur.fetchall()

    print("\n  NOW PRESENT")
    for name, bypass in rows:
        print(f"    {name}{'  <- BYPASSRLS' if bypass else ''}")
    if len(rows) != 2:
        print("\n  Expected two roles. Something did not take.")
        return 1

    host = pooled(parsed.hostname or "")
    if parsed.port:
        host = f"{host}:{parsed.port}"

    def url(role: str, password: str, hostname: str) -> str:
        return urllib.parse.urlunparse(
            (
                "postgresql+psycopg",
                f"{role}:{urllib.parse.quote(password, safe='')}@{hostname}",
                parsed.path,
                "",
                parsed.query,
                "",
            )
        )

    with open("app_url.txt", "w", encoding="utf-8") as handle:
        handle.write(url("dispatch_app", app_pw, host) + "\n")
    # dbt runs long scans; the direct endpoint suits that better than the pool.
    with open("analytics_url.txt", "w", encoding="utf-8") as handle:
        handle.write(url("dispatch_analytics", analytics_pw, parsed.hostname) + "\n")

    print("\n  Wrote app_url.txt       (pooled host, for Render)")
    print("  Wrote analytics_url.txt (direct host, for dbt)")
    print("\n  Next:")
    print("    uv run python check_app_url.py app_url.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
