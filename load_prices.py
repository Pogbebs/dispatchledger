"""Fetch EIA diesel prices and upsert them into raw_fuel_prices.

A standalone twin of the Airflow DAG's first two tasks, for the two places a
scheduler is the wrong tool: seeding a new database by hand, and the nightly
GitHub Actions run that replaces hosted Airflow in deployment.

Running a scheduler around the clock to fire four tasks once a day is the kind
of infrastructure that justifies itself in a diagram and not on an invoice.
The DAG stays in the repository because orchestration is worth demonstrating;
this is what actually runs in production.

    uv run python load_prices.py

Reads EIA_API_KEY, and the database from ANALYTICS_DATABASE_URL or
DATABASE_URL. Exits 2 with no key, so a caller can tell "no key configured"
from "the load failed".
"""

import os
import sys
from pathlib import Path

import psycopg

# The fetch logic is shared with the DAG rather than copied: one definition of
# which series, which window, and what counts as a usable row.
sys.path.insert(0, str(Path(__file__).resolve().parent / "pipelines" / "dags"))

from lib.eia import MissingApiKey, fetch_diesel_prices  # noqa: E402

UPSERT = """
    INSERT INTO raw_fuel_prices (series_id, price_date, price_usd_per_gal)
    VALUES (%s, %s, %s)
    ON CONFLICT (series_id, price_date)
    DO UPDATE SET
        price_usd_per_gal = EXCLUDED.price_usd_per_gal,
        loaded_at = now()
"""


def dsn() -> str:
    """A libpq connection string, from either URL form.

    The project holds SQLAlchemy URLs (postgresql+psycopg://) but psycopg
    wants a plain one. Accepting both means a deployment sets one variable and
    every consumer reads it, rather than maintaining two spellings of the same
    credential that can drift apart.
    """
    url = os.environ.get("ANALYTICS_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set ANALYTICS_DATABASE_URL or DATABASE_URL.")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def main() -> int:
    try:
        prices = fetch_diesel_prices()
    except MissingApiKey as exc:
        # Not a failure. The benchmark is an optional enrichment: without it
        # the warehouse still builds, the marts are simply empty of market
        # comparisons. Exiting 2 lets a workflow treat this as "skipped"
        # rather than turning a missing optional key into a red build that
        # people learn to ignore.
        print(f"skipped: {exc}", file=sys.stderr)
        return 2

    if not prices:
        print("EIA returned no usable rows; nothing to load.", file=sys.stderr)
        return 1

    rows = [
        (row["series_id"], row["price_date"], row["price_usd_per_gal"])
        for row in prices
    ]

    with psycopg.connect(dsn()) as conn, conn.cursor() as cur:
        cur.executemany(UPSERT, rows)
        conn.commit()

        cur.execute(
            "SELECT count(*), min(price_date), max(price_date), "
            "       min(price_usd_per_gal), max(price_usd_per_gal) "
            "FROM raw_fuel_prices"
        )
        count, first, last, low, high = cur.fetchone()

    # Printed because a load that says only "done" cannot be checked. These
    # five numbers are enough to see at a glance whether the window covers the
    # delivery history and whether the prices are plausible -- the two things
    # that were wrong the last time this data misled us.
    print(f"upserted {len(rows)} rows")
    print(f"raw_fuel_prices now holds {count} weeks, {first} to {last}")
    print(f"prices range ${low} to ${high}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
