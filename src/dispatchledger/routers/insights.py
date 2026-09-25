"""Pricing insights, read from the warehouse rather than the app tables.

Every other router in this application queries tables the API owns. This one
reads a dbt model -- and the interesting part is that it does so under exactly
the same tenant isolation as everything else.

That is not free. The marts are built by ``dispatch_analytics``, which holds
BYPASSRLS precisely so analytics can see across tenants. Handing the API that
credential would be the fastest possible way to undo the guarantee the rest of
the project is built on. So instead, ``agg_weekly_price_position`` carries its
own row-security policy (applied as a dbt post-hook, because dbt drops and
recreates the table on every run), and this router connects as ``dispatch_app``
like all the others.

The result is that the query below has no tenant filter in it, the same way
``list_customers`` has none.
"""

import os
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from dispatchledger.deps import get_session
from dispatchledger.schemas import InsightsOut, InsightsSummary, WeeklyPricePosition

router = APIRouter(prefix="/insights", tags=["insights"])

# dbt writes marts to <target schema>_marts. The value comes from the
# environment rather than a request, so interpolating it into SQL is safe --
# but it is pinned to a constant here rather than read per-call to keep that
# obviously true.
MARTS_SCHEMA = os.environ.get("ANALYTICS_MARTS_SCHEMA", "analytics_marts")
PRICE_POSITION = f"{MARTS_SCHEMA}.agg_weekly_price_position"

CENTS = Decimal("0.01")
MILS = Decimal("0.0001")


@router.get("", response_model=InsightsOut)
def price_position(
    session: Session = Depends(get_session),
    weeks: int = Query(default=26, ge=1, le=104),
) -> InsightsOut:
    """Weekly realised price against the national diesel benchmark.

    Returns the most recent ``weeks`` weeks in chronological order, plus a
    summary over exactly that window -- not over all history, so the headline
    figures always describe the same period as the chart underneath them.
    """
    # to_regclass returns NULL instead of raising for a table that does not
    # exist. Catching the error instead would leave the surrounding
    # transaction aborted and every later statement failing for the wrong
    # reason.
    exists = session.scalar(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": PRICE_POSITION})
    if not exists:
        return InsightsOut(warehouse_available=False, weeks=[], summary=None)

    rows = (
        session.execute(
            text(
                f"""
                SELECT week_start,
                       delivery_count,
                       delivered_gal,
                       revenue,
                       benchmark_revenue,
                       avg_price,
                       market_price,
                       price_delta,
                       margin_vs_benchmark
                FROM {PRICE_POSITION}
                ORDER BY week_start DESC
                LIMIT :limit
                """  # noqa: S608 -- schema is from the environment, limit is bound
            ),
            {"limit": weeks},
        )
        .mappings()
        .all()
    )

    if not rows:
        # The warehouse is built but holds nothing for this tenant: a new
        # company with no completed diesel deliveries yet, or a pipeline that
        # has never had an EIA key. Distinct from the table being absent.
        return InsightsOut(warehouse_available=True, weeks=[], summary=None)

    window = [
        WeeklyPricePosition(
            week_start=row["week_start"],
            delivery_count=row["delivery_count"],
            delivered_gal=row["delivered_gal"],
            revenue=row["revenue"],
            avg_price=row["avg_price"],
            market_price=row["market_price"],
            price_delta=row["price_delta"],
            margin_vs_benchmark=row["margin_vs_benchmark"],
        )
        for row in reversed(rows)  # oldest first, so the chart reads left to right
    ]

    return InsightsOut(
        warehouse_available=True,
        weeks=window,
        summary=_summarise(rows),
    )


def _summarise(rows: list) -> InsightsSummary:
    """Roll the window up the same way the model rolls deliveries up.

    Volume-weighted, for the same reason it is weighted in
    ``agg_weekly_price_position``: averaging the weekly averages would give a
    quiet week the same pull as a busy one. Doing it differently here than in
    the warehouse would produce a headline that disagrees with its own chart.
    """
    gallons = sum(row["delivered_gal"] for row in rows)
    revenue = sum(row["revenue"] for row in rows)
    benchmark_revenue = sum(row["benchmark_revenue"] for row in rows)
    weeks: list[date] = [row["week_start"] for row in rows]

    # Summed from the weekly figures rather than recomputed as
    # revenue - benchmark_revenue. The two differ by a few cents, because each
    # delivery's margin was rounded to cents before being summed, and
    # round(g*sell) - round(g*market) is not round(g*(sell-market)).
    #
    # Either is defensible on its own. Only one is defensible next to the
    # table underneath it, where the reader can add the column up by hand --
    # and a headline that disagrees with its own detail is the fastest way to
    # lose someone's trust in a report.
    margin = sum(row["margin_vs_benchmark"] for row in rows)

    divisor = gallons or Decimal(1)
    return InsightsSummary(
        weeks_covered=len(rows),
        delivery_count=sum(row["delivery_count"] for row in rows),
        delivered_gal=gallons,
        revenue=revenue.quantize(CENTS),
        avg_price=(revenue / divisor).quantize(MILS),
        market_price=(benchmark_revenue / divisor).quantize(MILS),
        price_delta=((revenue - benchmark_revenue) / divisor).quantize(MILS),
        margin_vs_benchmark=margin.quantize(CENTS),
        first_week=min(weeks),
        latest_week=max(weeks),
    )
