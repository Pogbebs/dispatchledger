"""analytics role and schema

Revision ID: 1d875ec9184d
Revises: 369c0108e8fd
Create Date: 2026-09-23 11:06:34.932962

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1d875ec9184d'
down_revision: Union[str, Sequence[str], None] = '369c0108e8fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # The deliberate exception to row-level security.
    #
    # Analytics has to read across every tenant -- that is the point of it --
    # so this role carries BYPASSRLS. It is separate from both the application
    # role and the owner so the exception is explicit, auditable, and easy to
    # revoke. It gets read on the application tables and full rights on its
    # own schema, and nothing else.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dispatch_analytics') THEN
                CREATE ROLE dispatch_analytics LOGIN PASSWORD 'dispatch_analytics' BYPASSRLS;
            ELSE
                ALTER ROLE dispatch_analytics BYPASSRLS;
            END IF;
        END
        $$;
        """
    )

    op.execute("CREATE SCHEMA IF NOT EXISTS analytics AUTHORIZATION dispatch_analytics")

    # dbt creates its own schemas (analytics_staging, analytics_marts, ...),
    # which needs CREATE on the database itself.
    op.execute("GRANT CREATE ON DATABASE dispatchledger TO dispatch_analytics")
    op.execute("GRANT USAGE ON SCHEMA public TO dispatch_analytics")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO dispatch_analytics")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO dispatch_analytics"
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS analytics CASCADE")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM dispatch_analytics"
    )
    op.execute("REVOKE SELECT ON ALL TABLES IN SCHEMA public FROM dispatch_analytics")
    op.execute("REVOKE USAGE ON SCHEMA public FROM dispatch_analytics")
    op.execute("REVOKE CREATE ON DATABASE dispatchledger FROM dispatch_analytics")
    op.execute("DROP ROLE IF EXISTS dispatch_analytics")