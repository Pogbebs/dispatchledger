"""Daily analytics pipeline for DispatchLedger.

    fetch external prices  ->  load to raw  ->  dbt build  ->  freshness check

dbt runs through its own virtualenv rather than Airflow's interpreter. The two
have genuinely incompatible pins -- Airflow holds click below the version dbt
requires -- so installing them together produces an environment where one of
them is subtly broken. Keeping dbt in /opt/dbt_venv and calling its binary is
the standard way out, and it means dbt can be upgraded without touching
Airflow.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pendulum
from airflow.exceptions import AirflowSkipException
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag, task

sys.path.insert(0, str(Path(__file__).parent))
from lib.eia import MissingApiKey, fetch_diesel_prices  # noqa: E402

log = logging.getLogger(__name__)

DBT_DIR = os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/analytics")
DBT_BIN = os.environ.get("DBT_BIN", "/opt/dbt_venv/bin/dbt")

DEFAULT_ARGS = {
    "owner": "analytics",
    "retries": 2,
    # Network calls fail transiently; a short backoff clears most of it
    # without masking a real outage.
    "retry_delay": timedelta(minutes=5),
    "depends_on_past": False,
}


def alert_on_failure(context) -> None:
    """Where a real deployment would page someone.

    Left as a log line on purpose: wiring this to Slack or PagerDuty needs
    credentials this project does not carry, and a fake integration would be
    worse than an honest placeholder.
    """
    task_instance = context.get("task_instance")
    log.error(
        "PIPELINE FAILURE: dag=%s task=%s run=%s -- would alert on-call here",
        context.get("dag").dag_id if context.get("dag") else "?",
        task_instance.task_id if task_instance else "?",
        context.get("run_id"),
    )


@dag(
    dag_id="dispatchledger_daily",
    description="Load external fuel prices, then rebuild and test the warehouse.",
    schedule="0 6 * * *",  # 06:00 UTC, after the prior day has closed out
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    on_failure_callback=alert_on_failure,
    tags=["dispatchledger", "analytics", "dbt"],
)
def dispatchledger_daily():
    @task(task_id="fetch_fuel_prices")
    def fetch_fuel_prices() -> list[dict]:
        """Pull the weekly national diesel benchmark from the EIA API.

        Without a key the task skips rather than fails: the benchmark is
        useful context, not a dependency of the core warehouse, and failing
        the whole run over a missing optional key would cry wolf.
        """
        try:
            prices = fetch_diesel_prices()
        except MissingApiKey as exc:
            raise AirflowSkipException(str(exc)) from exc

        if not prices:
            raise AirflowSkipException("EIA returned no usable prices for the window")

        return [
            {
                "price_date": row["price_date"],
                "price_usd_per_gal": str(row["price_usd_per_gal"]),
                "series_id": row["series_id"],
            }
            for row in prices
        ]

    @task(task_id="load_fuel_prices")
    def load_fuel_prices(prices: list[dict]) -> int:
        """Upsert into raw_fuel_prices, keyed on (series_id, price_date).

        Upsert rather than insert because the EIA revises recent weeks, and
        because a rerun of the same day must not double the rows. That makes
        the task idempotent, which is what lets Airflow retry it safely.
        """
        import psycopg

        dsn = os.environ["ANALYTICS_DATABASE_URL"]
        rows = [
            (row["series_id"], row["price_date"], row["price_usd_per_gal"])
            for row in prices
        ]

        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO raw_fuel_prices (series_id, price_date, price_usd_per_gal)
                VALUES (%s, %s, %s)
                ON CONFLICT (series_id, price_date)
                DO UPDATE SET
                    price_usd_per_gal = EXCLUDED.price_usd_per_gal,
                    loaded_at = now()
                """,
                rows,
            )
            conn.commit()

        log.info("Upserted %s benchmark prices", len(rows))
        return len(rows)

    # dbt build runs each model and its tests together, stopping a branch the
    # moment its tests fail. Running `dbt run` then `dbt test` would build
    # everything downstream of bad data before noticing.
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"cd {DBT_DIR} && {DBT_BIN} build --target prod",
        # The benchmark is optional, so a skipped fetch must not skip the
        # warehouse rebuild. Only an actual failure should stop this.
        trigger_rule="none_failed",
    )

    check_freshness = BashOperator(
        task_id="check_source_freshness",
        bash_command=f"cd {DBT_DIR} && {DBT_BIN} source freshness --target prod",
        # Stale sources are a warning about the world, not a broken pipeline,
        # so this runs last and does not fail the run on its own.
        trigger_rule="all_done",
    )

    prices = fetch_fuel_prices()
    load_fuel_prices(prices) >> dbt_build >> check_freshness


dispatchledger_daily()
