"""Rotate the dispatch_app password and write a fresh APP_DATABASE_URL.

dispatch_app was created by a migration, not by the Neon console, so Neon's
"Reset password" button does not govern it. Changing it means ALTER ROLE, run
as the database owner.

Doing that by hand means getting a generated password into a SQL statement and
then into a URL without a transcription error -- which is the failure mode this
project has hit more than any other. So this does all of it in one process: it
generates the password, sets it, assembles the connection string, and writes
that string to app_url.txt. The password is never displayed, never typed, and
never passes through the clipboard.

    uv run python rotate_app_password.py owner_url.txt

owner_url.txt holds the OWNER connection string -- the one Neon's Connect
button gives you, connecting as neondb_owner. Both that file and app_url.txt
hold live credentials; delete them when you are done.

The live app keeps using the old password until Render is updated, so it will
return errors between this script finishing and that variable being saved.
"""

import secrets
import sys
import urllib.parse

import psycopg
from psycopg import sql

APP_ROLE = "dispatch_app"
OUTPUT = "app_url.txt"


def first_line(path: str) -> str:
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        print(f"\nNo such file: {path}")
        print("Create it, paste the owner connection string on one line, save.")
        raise SystemExit(1) from None

    for line in lines:
        line = line.strip().strip('"').strip("'")
        if line and not line.startswith("#"):
            return line

    print(f"\n{path} has no connection string in it.")
    raise SystemExit(1)


def pooled(host: str) -> str:
    """Neon's pooled endpoint is the direct one with -pooler on the first label.

    Transaction-mode pooling is what makes SET LOCAL the right way to carry the
    tenant: the setting dies with the transaction, so a recycled connection
    cannot hand one tenant's identity to the next request.
    """
    if "-pooler" in host:
        return host
    head, _, tail = host.partition(".")
    return f"{head}-pooler.{tail}" if tail else host


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    owner = first_line(sys.argv[1])
    if not owner.startswith(("postgresql://", "postgresql+psycopg://")):
        print("\nThat does not look like a connection string.")
        return 1

    plain = owner.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urllib.parse.urlparse(plain)

    print(f"  owner role  {parsed.username}")
    print(f"  host        {parsed.hostname}")
    print(f"  database    {parsed.path.lstrip('/')}")

    if parsed.username == APP_ROLE:
        print(f"\n  That is the {APP_ROLE} string. This needs the OWNER string,")
        print("  because a role cannot reset a password it has lost.")
        return 1

    # url-safe alphabet: no characters that would need percent-encoding once
    # this lands in a connection string.
    password = secrets.token_urlsafe(24)

    print(f"\n  connecting as {parsed.username}...")
    try:
        with psycopg.connect(plain, connect_timeout=15, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(APP_ROLE), sql.Literal(password)
                    )
                )
    except psycopg.OperationalError as exc:
        print(f"\n  FAILED   {str(exc).strip().splitlines()[0]}")
        print("  The owner string is wrong. Re-copy it from Neon's Connect button.")
        return 1
    except psycopg.errors.UndefinedObject:
        print(f"\n  FAILED   the role {APP_ROLE} does not exist in this database.")
        print("  Check that the owner string points at the right database.")
        return 1

    print(f"  OK       {APP_ROLE} password changed")

    host = pooled(parsed.hostname or "")
    if parsed.port:
        host = f"{host}:{parsed.port}"

    app_url = urllib.parse.urlunparse(
        (
            "postgresql+psycopg",
            f"{APP_ROLE}:{urllib.parse.quote(password, safe='')}@{host}",
            parsed.path,
            "",
            parsed.query,
            "",
        )
    )

    with open(OUTPUT, "w", encoding="utf-8") as handle:
        handle.write(app_url + "\n")

    print(f"\n  Wrote {OUTPUT} ({len(app_url)} characters)")
    print(f"  host  {host}")
    print("\n  Next:")
    print(f"    uv run python check_app_url.py {OUTPUT}")
    print("    then paste the contents of app_url.txt into Render as APP_DATABASE_URL")
    print(f"    then: Remove-Item {OUTPUT}, Remove-Item {sys.argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
