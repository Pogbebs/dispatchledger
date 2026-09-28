"""analytics role and schema

Revision ID: 1d875ec9184d
Revises: 369c0108e8fd
Create Date: 2026-09-23 11:06:34.932962

"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1d875ec9184d'
down_revision: Union[str, Sequence[str], None] = '369c0108e8fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def role_password(env_var: str, dev_default: str) -> str:
    """A role's password as a quoted SQL literal. See 369c0108e8fd for why
    this is duplicated rather than imported."""
    value = os.environ.get(env_var) or dev_default
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    # The deliberate exception to row-level security.
    #
    # Analytics has to read across every tenant -- that is the point of it --
    # so this role carries BYPASSRLS. It is separate from both the application
    # role and the owner so the exception is explicit, auditable, and easy to
    # revoke. It gets read on the application tables and full rights on its
    # own schema, and nothing else.
    #
    # This is the credential that matters most: BYPASSRLS means the policies
    # protecting every other role do not apply to it. ANALYTICS_DB_PASSWORD is
    # not optional on anything reachable from the internet.
    password = role_password("ANALYTICS_DB_PASSWORD", "dispatch_analytics")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dispatch_analytics') THEN
                CREATE ROLE dispatch_analytics LOGIN PASSWORD {password} BYPASSRLS;
            ELSE
                ALTER ROLE dispatch_analytics LOGIN PASSWORD {password} BYPASSRLS;
            END IF;
        END
        $$;
        """
    )

    # Created by the migration's own role, then granted -- rather than
    # CREATE SCHEMA ... AUTHORIZATION dispatch_analytics.
    #
    # Creating a schema owned by another role requires being able to SET ROLE
    # to it. A local superuser can; the owner role on a managed provider
    # cannot, because it created dispatch_analytics through CREATEROLE rather
    # than being a superuser. The AUTHORIZATION form therefore works on a
    # laptop and fails on Neon with "must be able to SET ROLE".
    #
    # Ownership was never the requirement. dbt needs to create objects here,
    # which CREATE and USAGE grant directly, and it creates its own schemas
    # (analytics_staging, analytics_marts) under the CREATE ON DATABASE grant
    # below -- owning those, since it makes them.
    op.execute("CREATE SCHEMA IF NOT EXISTS analytics")
    op.execute("GRANT CREATE, USAGE ON SCHEMA analytics TO dispatch_analytics")

    # dbt creates its own schemas (analytics_staging, analytics_marts, ...),
    # which needs CREATE on the database itself.
    #
    # The database name is resolved at run time rather than written in. A
    # managed provider names the database for you -- Neon's default is
    # "neondb" -- and a hardcoded name fails here, half way through the
    # migration, with the role already created and nothing granted to it.
    op.execute(
        """
        DO $$
        BEGIN
            EXECUTE format(
                'GRANT CREATE ON DATABASE %I TO dispatch_analytics',
                current_database()
            );
        END
        $$;
        """
    )
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
    op.execute(
        """
        DO $$
        BEGIN
            EXECUTE format(
                'REVOKE CREATE ON DATABASE %I FROM dispatch_analytics',
                current_database()
            );
        END
        $$;
        """
    )
    op.execute("DROP ROLE IF EXISTS dispatch_analytics")
