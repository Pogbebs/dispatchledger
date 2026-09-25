"""Body for the external-benchmark migration.

Run:

    uv run alembic revision -m "raw fuel prices"

then replace the generated upgrade() and downgrade() with these, keeping the
revision headers at the top.
"""

from alembic import op


def upgrade() -> None:
    # Public reference data, not customer data: no tenant_id and no row-level
    # security, because the national diesel price is the same fact for
    # everyone. Every tenant reads the same rows by design.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_fuel_prices (
            series_id         text           NOT NULL,
            price_date        date           NOT NULL,
            price_usd_per_gal numeric(8, 4)  NOT NULL CHECK (price_usd_per_gal >= 0),
            loaded_at         timestamptz    NOT NULL DEFAULT now(),
            PRIMARY KEY (series_id, price_date)
        )
        """
    )

    # The composite primary key is what makes the loader idempotent: the
    # pipeline upserts on it, so a rerun updates rather than duplicates, and
    # revised weeks from the source overwrite cleanly.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_raw_fuel_prices_date ON raw_fuel_prices (price_date DESC)"
    )

    # The pipeline writes here as the analytics role; the application only reads.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON raw_fuel_prices TO dispatch_analytics"
    )
    op.execute("GRANT SELECT ON raw_fuel_prices TO dispatch_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS raw_fuel_prices")
