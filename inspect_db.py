"""Say what is actually in the database a connection string points at.

Written because two tools disagreed: one said dispatch_app could not
authenticate, the other said the role did not exist. Neon reports an unknown
role as an authentication failure -- it will not confirm whether a username
exists -- so an error message cannot settle it. Asking the catalog can.

    uv run python inspect_db.py owner_url.txt

Prints nothing secret: the host, the database, which login roles exist, and
whether the application's tables are present. Safe to paste into a chat.
"""

import sys
import urllib.parse

import psycopg

WANTED_ROLES = ("dispatch", "dispatch_app", "dispatch_analytics")
WANTED_TABLES = ("tenants", "customers", "orders", "deliveries", "invoices")


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


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    raw = first_line(sys.argv[1])
    plain = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urllib.parse.urlparse(plain)

    print(f"\n  host      {parsed.hostname}")
    print(f"  database  {parsed.path.lstrip('/')}")
    print(f"  as        {parsed.username}")

    try:
        conn = psycopg.connect(plain, connect_timeout=15)
    except psycopg.OperationalError as exc:
        print(f"\n  FAILED   {str(exc).strip().splitlines()[0]}")
        return 1

    with conn, conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_user, version()")
        database, user, version = cur.fetchone()
        print(f"\n  connected to {database} as {user}")
        print(f"  {version.split(' on ')[0]}")

        print("\n  LOGIN ROLES ON THIS BRANCH")
        cur.execute(
            "SELECT rolname, rolbypassrls FROM pg_roles "
            "WHERE rolcanlogin ORDER BY rolname"
        )
        found = cur.fetchall()
        for name, bypass in found:
            mark = "  <- BYPASSRLS" if bypass else ""
            print(f"    {name}{mark}")

        present = {name for name, _ in found}
        missing = [r for r in WANTED_ROLES if r not in present]

        print("\n  APPLICATION TABLES")
        for table in WANTED_TABLES:
            cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
            exists = cur.fetchone()[0] is not None
            count = ""
            if exists:
                cur.execute(f"SELECT count(*) FROM public.{table}")
                count = f"  ({cur.fetchone()[0]} rows)"
            print(f"    {table:<12} {'present' if exists else 'MISSING'}{count}")

        cur.execute(
            "SELECT count(*) FROM information_schema.schemata "
            "WHERE schema_name = 'analytics'"
        )
        print(f"\n  analytics schema: {'present' if cur.fetchone()[0] else 'missing'}")

    print()
    if missing:
        print(f"  MISSING ROLES: {', '.join(missing)}")
        print("  The migrations that create them have not run on this branch,")
        print("  or this is not the branch the live app uses.")
    else:
        print("  All three roles are here. This is the right branch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
