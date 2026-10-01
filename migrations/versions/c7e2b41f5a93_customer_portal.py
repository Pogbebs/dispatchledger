"""Customer portal: a role that sees one customer, not one tenant

Revision ID: c7e2b41f5a93
Revises: a3f1c8d24e07
Create Date: 2026-10-01

Staff see everything belonging to their distributor. A customer must see
strictly less: their own orders, sites and invoices, not their distributor's
other customers'.

The tempting approach is to widen the existing policy -- "match the tenant,
and also the customer if a customer setting is present". That inverts the
design. Every policy here fails closed: an unset setting matches nothing. A
policy that treats "no customer set" as "all customers" would fail open, and
a missed SET LOCAL would silently hand one customer their competitor's
pricing.

So the portal gets its own login role and its own policies:

* ``AS RESTRICTIVE`` means the new policy is ANDed with the tenant policy
  rather than ORed. Both must pass. A permissive policy would widen access;
  this narrows it.
* ``TO dispatch_portal`` scopes it to that role alone, so nothing staff do
  through ``dispatch_app`` changes, and no existing test changes.
* ``nullif(current_setting(...), '')::uuid`` is NULL when unset, and NULL
  matches no row. Same shape as the tenant policy, same failure direction.

Two columns and one table come with it.
"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7e2b41f5a93"
down_revision: Union[str, Sequence[str], None] = "a3f1c8d24e07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Every table a customer may read, and the column that ties a row to them.
# `customers` is keyed on its own id; the rest carry customer_id directly.
SCOPED: tuple[tuple[str, str], ...] = (
    ("customers", "id"),
    ("delivery_sites", "customer_id"),
    ("orders", "customer_id"),
    ("deliveries", "customer_id"),
    ("invoices", "customer_id"),
    # A customer may see the people at their own company, not the
    # distributor's staff directory.
    ("users", "customer_id"),
)

CURRENT_CUSTOMER = "nullif(current_setting('app.current_customer', true), '')::uuid"


def role_password(env_var: str, dev_default: str) -> str:
    """A role's password as a quoted SQL literal.

    Defined here rather than imported, for the same reason the earlier
    migrations define their own: a migration has to keep producing the same
    schema years after it was written.
    """
    value = os.environ.get(env_var) or dev_default
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    # ---- the customer a user belongs to --------------------------------
    #
    # Nullable, because staff have no customer. The CHECK ties the two
    # together so the pair cannot drift: a customer row without a customer,
    # or an admin that somehow has one, are both rejected by the database
    # rather than by whichever handler happens to remember.
    op.add_column(
        "users",
        sa.Column("customer_id", sa.UUID(), sa.ForeignKey("customers.id"), nullable=True),
    )
    op.create_index("ix_users_customer_id", "users", ["customer_id"])

    # 'customer' is a fourth role, and the existing constraint lists the
    # three it knows about. Widening it here rather than relaxing it to
    # anything-goes keeps a typo in a seed script a database error.
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('admin', 'dispatcher', 'driver', 'customer')",
    )
    op.create_check_constraint(
        "ck_users_customer_role",
        "users",
        "(role = 'customer') = (customer_id IS NOT NULL)",
    )

    # ---- the customer a delivery is for --------------------------------
    #
    # Denormalised, like tenant_id already is. A policy expressed as a
    # subquery into orders would run per row on every read; this is the same
    # trade the project already made one level up, for the same reason.
    op.add_column("deliveries", sa.Column("customer_id", sa.UUID(), nullable=True))

    # FORCE ROW LEVEL SECURITY applies policies to the table owner too, and
    # this backfill runs with no tenant set -- so it would match zero rows and
    # succeed, silently leaving every customer_id null. Lifted for the
    # statement, restored immediately.
    op.execute("ALTER TABLE deliveries NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        UPDATE deliveries d
           SET customer_id = o.customer_id
          FROM orders o
         WHERE o.id = d.order_id
        """
    )
    op.execute("ALTER TABLE deliveries FORCE ROW LEVEL SECURITY")

    op.alter_column("deliveries", "customer_id", nullable=False)
    op.create_foreign_key(
        "fk_deliveries_customer_id", "deliveries", "customers", ["customer_id"], ["id"]
    )
    op.create_index("ix_deliveries_customer_id", "deliveries", ["customer_id"])

    # ---- invitations ----------------------------------------------------
    #
    # A customer cannot sign themselves up: that would let anyone insert
    # themselves into a distributor's customer book. The distributor issues an
    # invitation and the customer only sets a password.
    #
    # Only the hash is stored. An invitation link is a credential until it is
    # used, and a table of live credentials in plaintext is the thing this
    # project exists to argue against.
    op.create_table(
        "customer_invites",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "customer_id", sa.UUID(), sa.ForeignKey("customers.id"), nullable=False
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_customer_invites_tenant_id", "customer_invites", ["tenant_id"])
    op.create_index(
        "ix_customer_invites_token_hash", "customer_invites", ["token_hash"], unique=True
    )

    # An invite is tenant data like everything else.
    op.execute("ALTER TABLE customer_invites ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE customer_invites FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON customer_invites "
        "USING (tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid) "
        "WITH CHECK (tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid)"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON customer_invites TO dispatch_app"
    )

    # ---- the portal role -------------------------------------------------
    #
    # Not a superuser, not an owner, and emphatically not BYPASSRLS. It is the
    # most constrained login in the system, which is correct: it is the only
    # one reachable by someone outside the distributor.
    password = role_password("PORTAL_DB_PASSWORD", "dispatch_portal")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dispatch_portal') THEN
                CREATE ROLE dispatch_portal LOGIN PASSWORD {password};
            ELSE
                ALTER ROLE dispatch_portal LOGIN PASSWORD {password};
            END IF;
        END
        $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO dispatch_portal")

    # Read-only everywhere except orders, where a customer may place one and
    # cancel one. No access at all to invites, which are a staff concern.
    for table in ("tenants", "products", "customers", "delivery_sites", "deliveries", "invoices", "users"):
        op.execute(f"GRANT SELECT ON {table} TO dispatch_portal")
    op.execute("GRANT SELECT, INSERT, UPDATE ON orders TO dispatch_portal")

    # ---- the restrictive policies ----------------------------------------
    for table, column in SCOPED:
        op.execute(f"DROP POLICY IF EXISTS customer_scope ON {table}")
        op.execute(
            f"CREATE POLICY customer_scope ON {table} "
            f"AS RESTRICTIVE FOR ALL TO dispatch_portal "
            f"USING ({column} = {CURRENT_CUSTOMER})"
        )


def downgrade() -> None:
    for table, _ in SCOPED:
        op.execute(f"DROP POLICY IF EXISTS customer_scope ON {table}")

    for table in ("tenants", "products", "customers", "delivery_sites", "deliveries", "invoices", "users"):
        op.execute(f"REVOKE ALL ON {table} FROM dispatch_portal")
    op.execute("REVOKE ALL ON orders FROM dispatch_portal")
    op.execute("REVOKE USAGE ON SCHEMA public FROM dispatch_portal")
    op.execute("DROP ROLE IF EXISTS dispatch_portal")

    op.drop_table("customer_invites")

    op.drop_index("ix_deliveries_customer_id", table_name="deliveries")
    op.drop_constraint("fk_deliveries_customer_id", "deliveries", type_="foreignkey")
    op.drop_column("deliveries", "customer_id")

    op.drop_constraint("ck_users_customer_role", "users", type_="check")
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role", "users", "role IN ('admin', 'dispatcher', 'driver')"
    )
    op.drop_index("ix_users_customer_id", table_name="users")
    op.drop_column("users", "customer_id")
