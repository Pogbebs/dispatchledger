"""Validate an APP_DATABASE_URL before trusting it to a deployment.

Paste a connection string at the prompt and this says whether it is well
formed and whether dispatch_app can actually connect with it.

Run it rather than setting shell variables: pasting a long secret into
PowerShell has gone wrong repeatedly -- prompts consuming the next pasted
line, quotes expanding variables, placeholders surviving into real values.
A prompt inside Python reads one line of standard input and leaves it alone.

    uv run python check_app_url.py
"""

import sys
import urllib.parse

import psycopg

EXPECTED_ROLE = "dispatch_app"


def complain(problem: str, fix: str) -> None:
    print(f"\n  PROBLEM  {problem}")
    print(f"  FIX      {fix}")


def read_from_file(path: str) -> str:
    """The first non-comment line of a file.

    Editing a 150-character secret in a text editor beats pasting it into a
    terminal: the whole value is visible at once, nothing expands variables
    or eats the next line, and a placeholder left behind is obvious on screen
    rather than hidden past the right edge.
    """
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        print(f"\nNo such file: {path}")
        print("Create it in VS Code, put the connection string on one line, save.")
        raise SystemExit(1) from None

    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            return line

    print(f"\n{path} has no connection string in it.")
    raise SystemExit(1)


def main() -> int:
    print(__doc__.strip().splitlines()[0])
    print()

    if len(sys.argv) > 1:
        raw = read_from_file(sys.argv[1]).strip()
        print(f"Read from {sys.argv[1]} ({len(raw)} characters)")
    else:
        raw = input("Paste the APP_DATABASE_URL you put into Render: ").strip()

    if not raw:
        print("\nNothing to check.")
        return 1

    # Strip quotes a copy-paste often brings along.
    raw = raw.strip('"').strip("'")

    problems = 0

    # Checks that do not need a network round trip. Each one has cost real
    # time at some point, so each gets named rather than being left for a
    # connection error to hint at.
    if "<" in raw or ">" in raw:
        complain("contains < or >", "that is placeholder text; delete the brackets and their contents")
        problems += 1
    if "$" in raw:
        complain("contains $", "a shell variable was never substituted; paste the literal value")
        problems += 1
    if raw.count("@") != 1:
        complain(f"has {raw.count('@')} '@' characters, expected 1",
                 "two strings were concatenated, or the password contains an unescaped @")
        problems += 1
    if not raw.startswith(("postgresql://", "postgresql+psycopg://")):
        complain("does not start with postgresql:// or postgresql+psycopg://",
                 "copy the string from Neon again")
        problems += 1

    if problems:
        print(f"\n{problems} problem(s) found. Fix those first.")
        return 1

    # psycopg wants the plain form; SQLAlchemy wants the +psycopg one. The
    # same credential, two spellings -- which is itself a recurring source of
    # confusion, so this converts rather than insisting.
    plain = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urllib.parse.urlparse(plain)

    print(f"\n  role      {parsed.username}")
    print(f"  host      {parsed.hostname}")
    print(f"  database  {parsed.path.lstrip('/')}")
    print(f"  options   {parsed.query or '(none)'}")

    if parsed.username != EXPECTED_ROLE:
        complain(f"connects as {parsed.username}, not {EXPECTED_ROLE}",
                 f"this variable is for the application role; change the user to {EXPECTED_ROLE}")
        return 1

    if parsed.hostname and "-pooler" not in parsed.hostname:
        print("\n  NOTE  this is the direct endpoint, not the pooled one.")
        print("        It will work, but the pooled host suits the request path better.")

    if "sslmode" not in (parsed.query or ""):
        complain("no sslmode in the query string", "a managed database will refuse a plaintext connection")
        return 1

    print("\n  connecting...")
    try:
        with psycopg.connect(plain, connect_timeout=15) as conn, conn.cursor() as cur:
            cur.execute("SELECT current_user, current_database()")
            who, where = cur.fetchone()
            cur.execute("SELECT count(*) FROM customers")
            visible = cur.fetchone()[0]
    except psycopg.OperationalError as exc:
        message = str(exc).strip().splitlines()[0]
        print(f"\n  FAILED   {message}")
        if "password authentication failed" in message:
            complain("the password does not match the role",
                     "run: ALTER ROLE dispatch_app PASSWORD '<the password in this string>'")
        elif "does not exist" in message:
            complain("the role or database does not exist",
                     "check the spelling of the user and the database name")
        elif "Name or service not known" in message or "could not translate" in message:
            complain("the hostname does not resolve", "re-copy the host from Neon")
        return 1

    print(f"\n  OK       connected as {who} to {where}")
    print(f"           sees {visible} customers with no tenant set")

    if visible != 0:
        print("\n  WARNING  an unset tenant should see ZERO rows.")
        print("           Row-level security is not applying to this role.")
        return 1

    print("\n  Row-level security is applying: zero rows without a tenant, as designed.")
    print("\n  Paste this into Render as APP_DATABASE_URL:\n")
    print("  " + plain.replace("postgresql://", "postgresql+psycopg://", 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
