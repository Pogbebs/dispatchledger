"""Let dispatch_analytics write the prices it ingests

Revision ID: a3f1c8d24e07
Revises: 1d875ec9184d
Create Date: 2026-10-01

dispatch_analytics was granted SELECT on everything in public and nothing
more, which is right for a role that reads the operational tables to build
marts. But it is also the role that loads the EIA benchmark, and the loader
upserts into raw_fuel_prices.

That gap never showed locally: load_prices.py falls back to DATABASE_URL when
ANALYTICS_DATABASE_URL is unset, so on a development machine the loader ran as
the owner and could write anywhere. The scheduled run is the first place it
connects as the analytics role, and the first place the missing grant became
a permission error.

raw_fuel_prices is public market data with no tenant column, so widening this
role's access to it gives up nothing: there is no tenant boundary here to
cross. The operational tables stay read-only to it.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a3f1c8d24e07"
down_revision: Union[str, Sequence[str], None] = "1d875ec9184d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# INSERT and UPDATE rather than ALL: the loader upserts, so it needs both, and
# nothing in the pipeline deletes a price. A benchmark that could be silently
# removed is a worse failure than one that cannot be corrected.
GRANT = (
    "GRANT SELECT, INSERT, UPDATE ON raw_fuel_prices TO dispatch_analytics"
)


def upgrade() -> None:
    op.execute(GRANT)


def downgrade() -> None:
    op.execute("REVOKE INSERT, UPDATE ON raw_fuel_prices FROM dispatch_analytics")
