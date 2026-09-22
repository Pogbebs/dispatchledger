"""Tenant isolation through the API.

The database-level proof lives in check_isolation.py. These tests assert the
guarantee survives the whole request path: token, dependency, handler, query.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from dispatchledger.db import admin_engine
from dispatchledger.models import Customer, Order


def _count(model, tenant_id) -> int:
    with Session(admin_engine) as session:
        return len(list(session.scalars(select(model.id).where(model.tenant_id == tenant_id))))


def test_listing_returns_only_your_tenant(client, admin_a, admin_b):
    ids_a = {c["id"] for c in client.get("/customers?limit=200", headers=admin_a).json()}
    ids_b = {c["id"] for c in client.get("/customers?limit=200", headers=admin_b).json()}

    assert ids_a and ids_b
    assert ids_a.isdisjoint(ids_b)


def test_listing_is_not_merely_empty(client, admin_a, tenant_a):
    """Guards against the opposite bug: a policy so tight nobody sees anything."""
    returned = len(client.get("/customers?limit=200", headers=admin_a).json())
    assert returned == _count(Customer, tenant_a.id)


def test_another_tenants_order_is_404(client, admin_a, order_id_b):
    """The id is real. It belongs to someone else. It must look absent."""
    response = client.get(f"/orders/{order_id_b}", headers=admin_a)
    assert response.status_code == 404


def test_another_tenants_customer_is_404(client, admin_a, customer_id_b):
    response = client.get(f"/customers/{customer_id_b}", headers=admin_a)
    assert response.status_code == 404


def test_owner_still_sees_their_own_order(client, admin_b, order_id_b):
    """The same id, with the right token, is found -- so 404 means isolation."""
    response = client.get(f"/orders/{order_id_b}", headers=admin_b)
    assert response.status_code == 200
    assert response.json()["id"] == str(order_id_b)


def test_cannot_cancel_another_tenants_order(client, admin_a, admin_b, order_id_b):
    before = client.get(f"/orders/{order_id_b}", headers=admin_b).json()["status"]
    assert client.post(f"/orders/{order_id_b}/cancel", headers=admin_a).status_code == 404
    after = client.get(f"/orders/{order_id_b}", headers=admin_b).json()["status"]
    assert after == before


def test_cannot_order_against_another_tenants_site(client, admin_a, tenant_b):
    """Foreign keys from another tenant read as missing, not as forbidden."""
    with Session(admin_engine) as session:
        order_b = session.scalar(select(Order).where(Order.tenant_id == tenant_b.id).limit(1))
        payload = {
            "customer_id": str(order_b.customer_id),
            "site_id": str(order_b.site_id),
            "product_id": str(order_b.product_id),
            "quantity_gal": "500.00",
            "requested_date": str(order_b.requested_date),
        }

    response = client.post("/orders", headers=admin_a, json=payload)
    assert response.status_code == 422


def test_tenant_comes_from_the_token_not_the_request(client, admin_a, tenant_b):
    """There is no tenant parameter to tamper with: the query string is ignored."""
    response = client.get(
        f"/customers?limit=200&tenant_id={tenant_b.id}",
        headers=admin_a,
    )
    ids = {c["id"] for c in response.json()}
    with Session(admin_engine) as session:
        ids_b = {str(i) for i in session.scalars(
            select(Customer.id).where(Customer.tenant_id == tenant_b.id)
        )}
    assert ids.isdisjoint(ids_b)
