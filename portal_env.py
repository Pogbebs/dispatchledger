"""Generate the two Render variables the customer portal needs.

The migration creates dispatch_portal with the password in PORTAL_DB_PASSWORD,
and the application connects with PORTAL_DATABASE_URL. The two have to carry
the same password, and they have to exist before the deploy that runs the
migration -- otherwise the role is created with the development default, which
is published in this repository.

Two values, one password, typed by nobody:

    uv run python portal_env.py owner_url.txt

Writes portal_env.txt with both lines ready to paste. It touches no database:
the migration sets the password, this only decides what it will be.

Delete the file once Render has the values.
"""

import secrets
import sys
import urllib.parse

OUTPUT = "portal_env.txt"


def first_line(path: str) -> str:
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        print(f"\nNo such file: {path}")
        print("Paste any of your Neon connection strings into it -- the host and")
        print("database name are all this reads.")
        raise SystemExit(1) from None
    for line in lines:
        line = line.strip().strip('"').strip("'")
        if line and not line.startswith("#"):
            return line
    print(f"\n{path} is empty.")
    raise SystemExit(1)


def pooled(host: str) -> str:
    """The portal serves requests, so it belongs on the pooled endpoint.

    Same reasoning as the application role: transaction-mode pooling is what
    makes SET LOCAL the right way to carry the tenant and the customer.
    """
    if "-pooler" in host:
        return host
    head, _, tail = host.partition(".")
    return f"{head}-pooler.{tail}" if tail else host


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    parsed = urllib.parse.urlparse(
        first_line(sys.argv[1]).replace("postgresql+psycopg://", "postgresql://", 1)
    )
    host = pooled(parsed.hostname or "")
    database = parsed.path.lstrip("/")
    if not host or not database:
        print("\nCould not read a host and database from that string.")
        return 1

    password = secrets.token_urlsafe(24)
    url = (
        f"postgresql+psycopg://dispatch_portal:"
        f"{urllib.parse.quote(password, safe='')}@{host}/{database}"
        f"?{parsed.query or 'sslmode=require'}"
    )

    with open(OUTPUT, "w", encoding="utf-8") as handle:
        handle.write(f"PORTAL_DB_PASSWORD={password}\n")
        handle.write(f"PORTAL_DATABASE_URL={url}\n")

    print(f"\n  host      {host}")
    print(f"  database  {database}")
    print(f"\n  Wrote {OUTPUT} with both values.")
    print("\n  Next:")
    print("    1. Render -> Environment -> add both, exactly as written")
    print("    2. Save, then push -- the migration reads PORTAL_DB_PASSWORD at startup")
    print("    3. Check /health returns ok: it now tries all three connections,")
    print("       so a wrong portal password fails the health check rather than")
    print("       waiting for a customer to find it")
    print(f"    4. Remove-Item {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
