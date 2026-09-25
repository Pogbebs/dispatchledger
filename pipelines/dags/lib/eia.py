"""Fetch US diesel prices from the EIA open data API.

Kept out of the DAG file so it can be tested on its own, and so the DAG
stays a description of orchestration rather than a pile of request handling.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from decimal import Decimal

import requests

log = logging.getLogger(__name__)

# Weekly US No 2 Diesel retail price, all sellers, dollars per gallon.
EIA_URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
SERIES_ID = "EMD_EPD2D_PTE_NUS_DPG"

REQUEST_TIMEOUT = 30


class MissingApiKey(RuntimeError):
    """Raised when EIA_API_KEY is not configured."""


def fetch_diesel_prices(lookback_days: int | None = None) -> list[dict]:
    """Return [{price_date, price_usd_per_gal, series_id}, ...], newest first.

    A free key from eia.gov/opendata is required. The caller decides what an
    absent key means -- this function refuses to invent data, because a
    benchmark nobody can trace is worse than no benchmark.
    """
    # Far enough back to cover the delivery history the warehouse holds.
    # Too short a window leaves older diesel deliveries with no market price
    # to compare against, which the coverage test then flags -- correctly, but
    # for a reason that is about the fetch rather than the data.
    if lookback_days is None:
        lookback_days = int(os.environ.get("EIA_LOOKBACK_DAYS", "400"))

    api_key = os.environ.get("EIA_API_KEY", "").strip()
    if not api_key:
        raise MissingApiKey(
            "EIA_API_KEY is not set. Get a free key at "
            "https://www.eia.gov/opendata/register.php"
        )

    start = (date.today() - timedelta(days=lookback_days)).isoformat()

    response = requests.get(
        EIA_URL,
        params={
            "api_key": api_key,
            "frequency": "weekly",
            "data[0]": "value",
            "facets[series][]": SERIES_ID,
            "start": start,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": 5000,
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    payload = response.json()
    rows = payload.get("response", {}).get("data", [])

    prices: list[dict] = []
    for row in rows:
        value = row.get("value")
        period = row.get("period")
        if value is None or period is None:
            # The API returns nulls for weeks it has not published yet.
            continue
        prices.append(
            {
                "price_date": period,
                "price_usd_per_gal": Decimal(str(value)),
                "series_id": SERIES_ID,
            }
        )

    log.info("EIA returned %s usable weekly prices since %s", len(prices), start)
    return prices
