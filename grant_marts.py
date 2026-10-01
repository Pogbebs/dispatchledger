"""Give dispatch_app read access to the dbt marts again.

When dispatch_app was dropped, every grant it held went with it. repair_roles
restored the ones on public and on the analytics schema, but dbt does not build
into 'analytics' -- dbt_project.yml appends a suffix per layer, so the models
land in analytics_staging, analytics_intermediate and analytics_marts. The
Insights endpoint reads one table in the last of those.

Grants only. No roles, no passwords, no schema changes, so nothing it does can
take the site down. Safe to run twice.

    uv run python grant_marts.py owner_url.txt
"""

import sys
import urllib.parse

import psycopg
from psycopg import sql

ROLE = "dispatch_app"


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
    print(f"\n  host      {parsed.hostname}")
    print(f"  database  {parsed.path.lstrip('/')}")

    try:
        conn = psycopg.connect(plain, connect_timeout=20, autocommit=True)
    except psycopg.OperationalError as exc:
        print(f"\n  FAILED   {str(exc).strip().splitlines()[0]}")
        return 1

    with conn, conn.cursor() as cur:
        # Every schema dbt might have built into, found rather than assumed --
        # the suffixes come from dbt_project.yml and could change.
        cur.execute(
            "SELECT nspname FROM pg_namespace "
            "WHERE nspname = 'analytics' OR nspname LIKE 'analytics\\_%' "
            "ORDER BY nspname"
        )
        schemas = [row[0] for row in cur.fetchall()]

        if not schemas:
            print("\n  No analytics schemas found. Has dbt ever run against this database?")
            return 1

        for schema in schemas:
            cur.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(ROLE)
                )
            )
            cur.execute(
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(ROLE)
                )
            )
            # dbt drops and recreates a table-materialized model on every run,
            # and a new table does not inherit the old one's grants. The model's
            # post_hook re-grants, but a default privilege covers anything built
            # by a path that forgets to.
            cur.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT ON TABLES TO {}"
                ).format(sql.Identifier(schema), sql.Identifier(ROLE))
            )
            cur.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname = %s", (schema,)
            )
            print(f"    {schema:<28} {cur.fetchone()[0]} tables")

        # The one the Insights page actually reads.
        cur.execute("SELECT to_regclass('analytics_marts.agg_weekly_price_position')")
        target = cur.fetchone()[0]

    print()
    if target is None:
        print("  analytics_marts.agg_weekly_price_position does not exist.")
        print("  The grants are in place, but dbt has not built that model here.")
        return 1

    print("  analytics_marts.agg_weekly_price_position is present and readable.")
    print("  Reload the Insights page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
