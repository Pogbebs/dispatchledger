"""Hand the dbt-built schemas back to dispatch_analytics.

dbt owns what it builds. Each run drops and recreates every view and table in
analytics_staging, analytics_intermediate and analytics_marts -- and dropping
an object requires owning it.

When dispatch_analytics was dropped from the database, Postgres could not drop
the schemas with it, so they were transferred to the database owner. The
recreated role can read them and cannot replace them, which stops dbt at the
first staging model. Granting CREATE would not help: the problem is the DROP,
not the CREATE.

So remove them. dbt recreates each one on the next run, owned by the role that
built it, and the marts' post-hooks re-apply their row-security policies and
their grants to dispatch_app as they go.

Nothing operational lives in these schemas -- they hold only derived models,
rebuilt from public every run. The source tables are untouched.

    uv run python reset_dbt_schemas.py owner_url.txt

Between this and the next successful dbt run the Insights page returns errors,
because the mart it reads will not exist. Run the workflow straight afterwards.
"""

import sys
import urllib.parse

import psycopg
from psycopg import sql

ROLE = "dispatch_analytics"
# The bare 'analytics' schema is created by a migration and is not dbt's to
# manage, so it is deliberately not in this list.
SUFFIXED = "analytics\\_%"


def first_line(path: str) -> str:
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        print(f"\nNo such file: {path}")
        print("Paste the owner connection string into it from Neon's Connect button.")
        raise SystemExit(1) from None
    for line in lines:
        line = line.strip().strip('"').strip("'")
        if line and not line.startswith("#"):
            return line
    print(f"\n{path} is empty.")
    raise SystemExit(1)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    plain = first_line(sys.argv[1]).replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urllib.parse.urlparse(plain)
    database = parsed.path.lstrip("/")
    print(f"\n  host      {parsed.hostname}")
    print(f"  database  {database}")

    try:
        conn = psycopg.connect(plain, connect_timeout=20, autocommit=True)
    except psycopg.OperationalError as exc:
        print(f"\n  FAILED   {str(exc).strip().splitlines()[0]}")
        return 1

    with conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,))
        if cur.fetchone() is None:
            print(f"\n  {ROLE} does not exist. Run repair_roles.py first.")
            return 1

        # dbt creates a schema it is told to write to, as long as it may create
        # schemas in the database at all.
        cur.execute(
            sql.SQL("GRANT CREATE ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(ROLE)
            )
        )

        cur.execute(
            "SELECT n.nspname, pg_get_userbyid(n.nspowner), count(c.oid) "
            "FROM pg_namespace n "
            "LEFT JOIN pg_class c ON c.relnamespace = n.oid "
            "WHERE n.nspname LIKE %s "
            "GROUP BY n.nspname, n.nspowner ORDER BY n.nspname",
            (SUFFIXED,),
        )
        found = cur.fetchall()

        if not found:
            print("\n  No dbt schemas present. The next run will create them.")
            return 0

        print()
        for schema, owner, objects in found:
            print(f"    {schema:<28} owned by {owner:<16} {objects} objects")

        print()
        for schema, _, _ in found:
            cur.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )
            print(f"    dropped {schema}")

    print("\n  Done. Run the Nightly warehouse workflow now.")
    print("  dbt will recreate all three, owned by dispatch_analytics, and the")
    print("  marts' post-hooks will re-apply their policies and grants.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
