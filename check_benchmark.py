"""Why the Insights page says there is nothing to benchmark.

The margin figure needs three things to line up: EIA prices loaded, completed
diesel deliveries, and an overlap between their dates. An empty Insights page
means one of those is missing, and the page cannot say which -- it only knows
the mart came back with no rows.

    uv run python check_benchmark.py owner_url.txt

Read-only, and prints nothing secret. Safe to screenshot.
"""

import sys
import urllib.parse

import psycopg

QUESTIONS = (
    (
        "EIA prices loaded",
        "SELECT count(*), min(price_date)::text, max(price_date)::text "
        "FROM raw_fuel_prices",
    ),
    (
        "Completed deliveries",
        "SELECT count(*), min(delivered_at)::date::text, max(delivered_at)::date::text "
        "FROM deliveries WHERE status = 'completed'",
    ),
    (
        "Diesel orders delivered",
        "SELECT count(*), min(o.requested_date)::text, max(o.requested_date)::text "
        "FROM orders o JOIN products p ON p.id = o.product_id "
        "WHERE o.status = 'delivered' AND p.name ILIKE '%diesel%'",
    ),
)


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

    plain = first_line(sys.argv[1]).replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urllib.parse.urlparse(plain)
    print(f"\n  host      {parsed.hostname}")
    print(f"  database  {parsed.path.lstrip('/')}")

    try:
        conn = psycopg.connect(plain, connect_timeout=20)
    except psycopg.OperationalError as exc:
        print(f"\n  FAILED   {str(exc).strip().splitlines()[0]}")
        return 1

    with conn, conn.cursor() as cur:
        print("\n  SOURCES")
        for label, sql in QUESTIONS:
            count, earliest, latest = cur.execute(sql).fetchone()
            span = f"{earliest} to {latest}" if count else "none"
            print(f"    {label:<24} {count:>6}   {span}")

        print("\n  THE MART")
        cur.execute("SELECT to_regclass('analytics_marts.agg_weekly_price_position')")
        if cur.fetchone()[0] is None:
            print("    agg_weekly_price_position is missing -- dbt has not built it.")
            return 1

        cur.execute(
            "SELECT count(*), "
            "       count(*) FILTER (WHERE market_price IS NOT NULL), "
            "       min(week_start)::text, max(week_start)::text "
            "FROM analytics_marts.agg_weekly_price_position"
        )
        rows, benchmarked, earliest, latest = cur.fetchone()
        print(f"    rows                     {rows:>6}")
        print(f"    with a market price      {benchmarked:>6}")
        if rows:
            print(f"    weeks covered            {earliest} to {latest}")

    print()
    if rows and benchmarked:
        print("  Benchmarked rows exist. If the page is empty, the window is too")
        print("  short -- try a longer period in the dropdown.")
    elif rows:
        print("  The mart has delivery weeks but no market price against them.")
        print("  The EIA dates and the delivery dates do not overlap: compare the")
        print("  two ranges above.")
    else:
        print("  The mart is empty. Either no deliveries are completed, or dbt")
        print("  built before the data it reads existed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
