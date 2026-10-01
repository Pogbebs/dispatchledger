"""Database engines and the tenant-scoped session.

Two engines, deliberately:

* ``app_engine`` connects as ``dispatch_app`` -- not a superuser, owns nothing,
  so row-level security applies to it. Every request uses this.
* ``admin_engine`` connects as the owner and bypasses RLS. It is used only by
  the login endpoint, which must find a tenant and a user before any tenant is
  known, and by migrations and seeding.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from dispatchledger.config import (
    ADMIN_DATABASE_URL,
    APP_DATABASE_URL,
    PORTAL_DATABASE_URL,
)

app_engine = create_engine(APP_DATABASE_URL, pool_pre_ping=True)
admin_engine = create_engine(ADMIN_DATABASE_URL, pool_pre_ping=True)
portal_engine = create_engine(PORTAL_DATABASE_URL, pool_pre_ping=True)

# Kept for seeding and scripts that legitimately work across tenants.
SessionLocal = sessionmaker(bind=admin_engine)
engine = admin_engine


@contextmanager
def tenant_session(tenant_id: uuid.UUID | str) -> Iterator[Session]:
    """A session scoped to one tenant for the life of one transaction.

    ``set_config(..., true)`` is the function form of ``SET LOCAL``: the
    setting is bound to the transaction and disappears when it ends. That
    matters because connections are pooled and reused. A session-level ``SET``
    would survive into whichever request picked up the connection next, and
    that request would silently read the previous tenant's rows.
    """
    with Session(app_engine) as session:
        with session.begin():
            session.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(tenant_id)},
            )
            yield session


@contextmanager
def customer_session(
    tenant_id: uuid.UUID | str, customer_id: uuid.UUID | str
) -> Iterator[Session]:
    """A session scoped to one customer inside one tenant.

    Connects as ``dispatch_portal``, which carries a restrictive policy on top
    of the tenant policy. Restrictive means ANDed, not ORed: both have to pass,
    so this connection can never see more than the staff connection would, only
    less.

    Both settings are transaction-scoped for the same reason as the tenant
    alone. Either one left unset is NULL, and NULL matches no row -- so a
    failure here shows up as an empty screen, never as another customer's
    orders.
    """
    with Session(portal_engine) as session:
        with session.begin():
            session.execute(
                text(
                    "SELECT set_config('app.current_tenant', :tenant, true), "
                    "       set_config('app.current_customer', :customer, true)"
                ),
                {"tenant": str(tenant_id), "customer": str(customer_id)},
            )
            yield session


@contextmanager
def admin_session() -> Iterator[Session]:
    """Bypasses row-level security. Only for login, migrations and seeding."""
    with Session(admin_engine) as session:
        yield session
