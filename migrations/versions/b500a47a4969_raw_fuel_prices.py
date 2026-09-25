"""raw fuel prices

Revision ID: b500a47a4969
Revises: 1d875ec9184d
Create Date: 2026-09-23 14:01:21.247193

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b500a47a4969'
down_revision: Union[str, Sequence[str], None] = '1d875ec9184d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    # pipeline upserts on it, so a rerun updates rather than duplicates.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_raw_fuel_prices_date ON raw_fuel_prices (price_date DESC)"
    )

    # The pipeline writes here as the analytics role; the application only reads.
    op.execute("GRANT SELECT, INSERT, UPDATE ON raw_fuel_prices TO dispatch_analytics")
    op.execute("GRANT SELECT ON raw_fuel_prices TO dispatch_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS raw_fuel_prices")