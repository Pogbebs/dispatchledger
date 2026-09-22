"""row level security

Revision ID: 369c0108e8fd
Revises: f669781c19e5
Create Date: 2026-09-22 10:44:13.075249

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '369c0108e8fd'
down_revision: Union[str, Sequence[str], None] = 'f669781c19e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_TABLES = (
    "users",
    "customers",
    "delivery_sites",
    "products",
    "orders",
    "deliveries",
    "invoices",
)

TENANT_PREDICATE = (
    "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
)


def upgrade() -> None:
    # An application login role. Deliberately not a superuser and not the table
    # owner, because Postgres lets superusers bypass row-level security
    # entirely -- the API connects as this role so the policies actually apply.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dispatch_app') THEN
                CREATE ROLE dispatch_app LOGIN PASSWORD 'dispatch_app';
            END IF;
        END
        $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO dispatch_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO dispatch_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dispatch_app"
    )

    # current_setting(..., true) returns NULL when the setting is absent, and
    # NULL = anything is NULL, so a request that forgets to set the tenant sees
    # zero rows instead of everything. Fail closed, not open.
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )

    # tenants has no tenant_id: its own id is the tenant.
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON tenants "
        "USING (id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenants")
    op.execute("ALTER TABLE tenants DISABLE ROW LEVEL SECURITY")

    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM dispatch_app"
    )
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM dispatch_app"
    )
    op.execute("REVOKE USAGE ON SCHEMA public FROM dispatch_app")
    op.execute("DROP ROLE IF EXISTS dispatch_app")