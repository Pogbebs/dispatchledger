"""Shared fixtures. Tests run against the seeded development database."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from dispatchledger.db import admin_engine
from dispatchledger.main import app
from dispatchledger.models import Customer, Order, Tenant

PASSWORD = "demo1234"


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="session")
def tenants() -> list[Tenant]:
    with Session(admin_engine) as session:
        rows = list(session.scalars(select(Tenant).order_by(Tenant.slug)))
        if len(rows) < 2:
            pytest.skip("Run seed.py first: these tests need two seeded tenants.")
        session.expunge_all()
        return rows


def _token(client: TestClient, slug: str, email_prefix: str) -> str:
    response = client.post(
        "/login",
        json={
            "tenant_slug": slug,
            "email": f"{email_prefix}@{slug}.example.com",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture(scope="session")
def tenant_a(tenants) -> Tenant:
    return tenants[0]


@pytest.fixture(scope="session")
def tenant_b(tenants) -> Tenant:
    return tenants[1]


@pytest.fixture(scope="session")
def admin_a(client, tenant_a) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(client, tenant_a.slug, 'admin')}"}


@pytest.fixture(scope="session")
def admin_b(client, tenant_b) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(client, tenant_b.slug, 'admin')}"}


@pytest.fixture(scope="session")
def driver_a(client, tenant_a) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(client, tenant_a.slug, 'driver1')}"}


def _first_id(model, tenant_id):
    with Session(admin_engine) as session:
        return session.scalar(select(model.id).where(model.tenant_id == tenant_id).limit(1))


@pytest.fixture(scope="session")
def order_id_b(tenant_b):
    return _first_id(Order, tenant_b.id)


@pytest.fixture(scope="session")
def customer_id_b(tenant_b):
    return _first_id(Customer, tenant_b.id)


@pytest.fixture(scope="session")
def customer_a(client, tenant_a) -> dict[str, str]:
    """A portal login for the first customer of tenant A."""
    return {"Authorization": f"Bearer {_token(client, tenant_a.slug, 'portal')}"}


@pytest.fixture(scope="session")
def customer_b(client, tenant_b) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(client, tenant_b.slug, 'portal')}"}


@pytest.fixture(scope="session")
def customer_a_id(client, customer_a) -> str:
    """Which customer that login belongs to, read from the server's own answer.

    Taken from /me rather than from the database, so the test depends on the
    same path the application does.
    """
    response = client.get("/me", headers=customer_a)
    assert response.status_code == 200, response.text
    customer_id = response.json()["customer_id"]
    if customer_id is None:
        pytest.skip("Seeded portal user has no customer; re-run seed.py.")
    return customer_id
