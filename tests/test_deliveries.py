"""Delivery completion, invoicing, and the connection-pool leak check."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from dispatchledger.db import admin_engine
from dispatchledger.models import Customer, DeliverySite, Invoice, Order, Product, User


def _fixtures_for(tenant_id):
    with Session(admin_engine) as session:
        site = session.scalar(
            select(DeliverySite).where(DeliverySite.tenant_id == tenant_id).limit(1)
        )
        product = session.scalar(
            select(Product).where(Product.tenant_id == tenant_id).limit(1)
        )
        drivers = list(
            session.scalars(
                select(User).where(User.tenant_id == tenant_id, User.role == "driver")
            )
        )
        return {
            "customer_id": str(site.customer_id),
            "site_id": str(site.id),
            "product_id": str(product.id),
            "price": product.current_price,
            "driver_ids": [str(d.id) for d in drivers],
        }


def _driver_id_for(client, headers) -> str:
    return client.get("/me", headers=headers).json()["id"]


def test_order_snapshots_the_current_price(client, admin_a, tenant_a):
    f = _fixtures_for(tenant_a.id)
    response = client.post(
        "/orders",
        headers=admin_a,
        json={
            "customer_id": f["customer_id"],
            "site_id": f["site_id"],
            "product_id": f["product_id"],
            "quantity_gal": "1000.00",
            "requested_date": str(date.today()),
        },
    )
    assert response.status_code == 201
    assert Decimal(response.json()["unit_price"]) == f["price"]
    assert response.json()["status"] == "pending"


def test_delivery_completes_and_bills_delivered_gallons(client, admin_a, driver_a, tenant_a):
    f = _fixtures_for(tenant_a.id)
    driver_id = _driver_id_for(client, driver_a)

    order = client.post(
        "/orders",
        headers=admin_a,
        json={
            "customer_id": f["customer_id"],
            "site_id": f["site_id"],
            "product_id": f["product_id"],
            "quantity_gal": "2000.00",
            "requested_date": str(date.today()),
        },
    ).json()

    delivery = client.post(
        "/deliveries",
        headers=admin_a,
        json={
            "order_id": order["id"],
            "driver_id": driver_id,
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert delivery.status_code == 201
    delivery_id = delivery.json()["id"]

    # The truck left 120 gallons short, which is the normal case.
    completed = client.post(
        f"/deliveries/{delivery_id}/complete",
        headers=driver_a,
        json={"delivered_gal": "1880.00"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    with Session(admin_engine) as session:
        invoice = session.scalar(select(Invoice).where(Invoice.delivery_id == delivery_id))
        expected = (Decimal("1880.00") * Decimal(order["unit_price"])).quantize(Decimal("0.01"))
        assert invoice is not None
        # Billed on what arrived, not on what was ordered.
        assert invoice.amount == expected
        assert invoice.status == "unpaid"

        customer = session.get(Customer, invoice.customer_id)
        assert invoice.due_date == invoice.issued_at + timedelta(
            days=customer.payment_terms_days
        )

        refreshed = session.get(Order, order["id"])
        assert refreshed.status == "delivered"


def test_completing_twice_conflicts(client, admin_a, driver_a, tenant_a):
    f = _fixtures_for(tenant_a.id)
    driver_id = _driver_id_for(client, driver_a)
    order = client.post(
        "/orders",
        headers=admin_a,
        json={
            "customer_id": f["customer_id"],
            "site_id": f["site_id"],
            "product_id": f["product_id"],
            "quantity_gal": "600.00",
            "requested_date": str(date.today()),
        },
    ).json()
    delivery_id = client.post(
        "/deliveries",
        headers=admin_a,
        json={
            "order_id": order["id"],
            "driver_id": driver_id,
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
        },
    ).json()["id"]

    body = {"delivered_gal": "600.00"}
    assert client.post(f"/deliveries/{delivery_id}/complete", headers=driver_a, json=body).status_code == 200
    assert client.post(f"/deliveries/{delivery_id}/complete", headers=driver_a, json=body).status_code == 409


def test_driver_cannot_schedule_a_delivery(client, driver_a, tenant_a):
    f = _fixtures_for(tenant_a.id)
    response = client.post(
        "/deliveries",
        headers=driver_a,
        json={
            "order_id": f["site_id"],  # value is irrelevant: the role check runs first
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert response.status_code == 403


def test_driver_cannot_complete_someone_elses_delivery(client, admin_a, driver_a, tenant_a):
    f = _fixtures_for(tenant_a.id)
    mine = _driver_id_for(client, driver_a)
    other = next(d for d in f["driver_ids"] if d != mine)

    order = client.post(
        "/orders",
        headers=admin_a,
        json={
            "customer_id": f["customer_id"],
            "site_id": f["site_id"],
            "product_id": f["product_id"],
            "quantity_gal": "800.00",
            "requested_date": str(date.today()),
        },
    ).json()
    delivery_id = client.post(
        "/deliveries",
        headers=admin_a,
        json={
            "order_id": order["id"],
            "driver_id": other,
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
        },
    ).json()["id"]

    response = client.post(
        f"/deliveries/{delivery_id}/complete",
        headers=driver_a,
        json={"delivered_gal": "800.00"},
    )
    assert response.status_code == 403


def test_pooled_connections_do_not_leak_the_tenant(client, admin_a, admin_b):
    """The reason app.current_tenant is set with SET LOCAL, not SET.

    Connections are reused between requests. If the setting outlived its
    transaction, a request would inherit whichever tenant touched that
    connection last. Alternating tenants repeatedly is what surfaces it.
    """
    baseline_a = {c["id"] for c in client.get("/customers?limit=200", headers=admin_a).json()}
    baseline_b = {c["id"] for c in client.get("/customers?limit=200", headers=admin_b).json()}
    assert baseline_a.isdisjoint(baseline_b)

    for _ in range(15):
        seen_a = {c["id"] for c in client.get("/customers?limit=200", headers=admin_a).json()}
        seen_b = {c["id"] for c in client.get("/customers?limit=200", headers=admin_b).json()}
        assert seen_a == baseline_a
        assert seen_b == baseline_b
