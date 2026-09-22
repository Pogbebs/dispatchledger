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

from dispatchledger.config import ADMIN_DATABASE_URL, APP_DATABASE_URL

app_engine = create_engine(APP_DATABASE_URL, pool_pre_ping=True)
admin_engine = create_engine(ADMIN_DATABASE_URL, pool_pre_ping=True)

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
def admin_session() -> Iterator[Session]:
    """Bypasses row-level security. Only for login, migrations and seeding."""
    with Session(admin_engine) as session:
        yield session
