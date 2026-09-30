"""Scheduling a delivery and reassigning one.

These close the gap between an order and a delivery. Until the endpoints
existed in the UI, every delivery in the system had come from seed.py, so the
path a dispatcher actually walks had never been exercised end to end.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from dispatchledger.db import admin_engine
from dispatchledger.models import Customer, DeliverySite, Order, Product, User


def _tomorrow() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


def _new_order(client, headers) -> str:
    """A fresh pending order, created through the API like a dispatcher would."""
    customers = client.get("/customers?limit=1", headers=headers).json()
    products = client.get("/products", headers=headers).json()
    sites = client.get(f"/sites?customer_id={customers[0]['id']}", headers=headers).json()
    if not sites:
        pytest.skip("Seeded customer has no delivery site.")

    response = client.post(
        "/orders",
        headers=headers,
        json={
            "customer_id": customers[0]["id"],
            "site_id": sites[0]["id"],
            "product_id": products[0]["id"],
            "quantity_gal": "1500.00",
            "requested_date": datetime.now(timezone.utc).date().isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _driver_ids(client, headers) -> list[str]:
    return [d["id"] for d in client.get("/drivers", headers=headers).json()]


# ---------- the drivers list ----------

def test_drivers_returns_only_drivers(client, admin_a, tenant_a):
    """An admin is a user too. The dropdown must not offer one as a driver."""
    returned = {d["id"] for d in client.get("/drivers", headers=admin_a).json()}
    assert returned

    with Session(admin_engine) as session:
        actual = {
            str(i)
            for i in session.scalars(
                select(User.id).where(
                    User.tenant_id == tenant_a.id, User.role == "driver"
                )
            )
        }
    assert returned == actual


def test_drivers_are_tenant_scoped(client, admin_a, admin_b):
    a = {d["id"] for d in client.get("/drivers", headers=admin_a).json()}
    b = {d["id"] for d in client.get("/drivers", headers=admin_b).json()}
    assert a and b
    assert a.isdisjoint(b)


def test_drivers_expose_no_contact_details(client, admin_a):
    """Name and id are what scheduling needs; email is a staff directory."""
    for driver in client.get("/drivers", headers=admin_a).json():
        assert set(driver) == {"id", "full_name"}


# ---------- scheduling ----------

def test_scheduling_a_delivery_moves_the_order(client, admin_a):
    order_id = _new_order(client, admin_a)
    drivers = _driver_ids(client, admin_a)

    response = client.post(
        "/deliveries",
        headers=admin_a,
        json={
            "order_id": order_id,
            "driver_id": drivers[0],
            "scheduled_at": _tomorrow(),
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["driver_id"] == drivers[0]

    with Session(admin_engine) as session:
        assert session.get(Order, uuid.UUID(order_id)).status == "scheduled"


def test_scheduling_without_a_driver_is_allowed(client, admin_a):
    """A run can be put on the board before anyone is free to take it."""
    order_id = _new_order(client, admin_a)
    response = client.post(
        "/deliveries",
        headers=admin_a,
        json={"order_id": order_id, "driver_id": None, "scheduled_at": _tomorrow()},
    )
    assert response.status_code == 201, response.text
    assert response.json()["driver_id"] is None


def test_cannot_assign_a_non_driver(client, admin_a, tenant_a):
    """driver_id is just a user id, so the schema cannot stop this. The
    handler has to."""
    with Session(admin_engine) as session:
        admin_id = session.scalar(
            select(User.id).where(User.tenant_id == tenant_a.id, User.role == "admin")
        )

    order_id = _new_order(client, admin_a)
    response = client.post(
        "/deliveries",
        headers=admin_a,
        json={
            "order_id": order_id,
            "driver_id": str(admin_id),
            "scheduled_at": _tomorrow(),
        },
    )
    assert response.status_code == 422
    assert "not a driver" in response.json()["detail"]


def test_cannot_assign_another_tenants_driver(client, admin_a, admin_b):
    """The id is real. It belongs to someone else. It must look absent.

    Nothing in the handler compares tenants -- the lookup runs under the
    row-security policy, so the other tenant's driver simply is not there.
    """
    other_driver = _driver_ids(client, admin_b)[0]
    order_id = _new_order(client, admin_a)

    response = client.post(
        "/deliveries",
        headers=admin_a,
        json={
            "order_id": order_id,
            "driver_id": other_driver,
            "scheduled_at": _tomorrow(),
        },
    )
    assert response.status_code == 404


def test_drivers_cannot_schedule(client, driver_a):
    """Drivers complete runs. They do not hand them out."""
    response = client.post(
        "/deliveries",
        headers=driver_a,
        json={"order_id": str(uuid.uuid4()), "scheduled_at": _tomorrow()},
    )
    assert response.status_code == 403


# ---------- reassignment ----------

def _scheduled_delivery(client, headers) -> dict:
    order_id = _new_order(client, headers)
    return client.post(
        "/deliveries",
        headers=headers,
        json={"order_id": order_id, "scheduled_at": _tomorrow()},
    ).json()


def test_reassigning_changes_the_driver(client, admin_a):
    delivery = _scheduled_delivery(client, admin_a)
    drivers = _driver_ids(client, admin_a)

    response = client.patch(
        f"/deliveries/{delivery['id']}",
        headers=admin_a,
        json={"driver_id": drivers[-1]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["driver_id"] == drivers[-1]


def test_explicit_null_unassigns(client, admin_a):
    """Absent and null mean different things, which is why the handler reads
    model_fields_set rather than checking for None."""
    order_id = _new_order(client, admin_a)
    drivers = _driver_ids(client, admin_a)
    delivery = client.post(
        "/deliveries",
        headers=admin_a,
        json={
            "order_id": order_id,
            "driver_id": drivers[0],
            "scheduled_at": _tomorrow(),
        },
    ).json()

    response = client.patch(
        f"/deliveries/{delivery['id']}", headers=admin_a, json={"driver_id": None}
    )
    assert response.status_code == 200
    assert response.json()["driver_id"] is None


def test_rescheduling_changes_the_date_only(client, admin_a):
    delivery = _scheduled_delivery(client, admin_a)
    drivers = _driver_ids(client, admin_a)
    client.patch(
        f"/deliveries/{delivery['id']}", headers=admin_a, json={"driver_id": drivers[0]}
    )

    later = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    response = client.patch(
        f"/deliveries/{delivery['id']}", headers=admin_a, json={"scheduled_at": later}
    )
    assert response.status_code == 200
    # The driver was not in the payload, so it must be untouched.
    assert response.json()["driver_id"] == drivers[0]


def test_empty_patch_is_rejected(client, admin_a):
    delivery = _scheduled_delivery(client, admin_a)
    response = client.patch(f"/deliveries/{delivery['id']}", headers=admin_a, json={})
    assert response.status_code == 400


def test_cannot_reschedule_a_completed_delivery(client, admin_a):
    """The invoice is written against it. Moving it afterwards would put the
    billing record and the delivery record into disagreement."""
    delivery = _scheduled_delivery(client, admin_a)
    client.post(
        f"/deliveries/{delivery['id']}/complete",
        headers=admin_a,
        json={"delivered_gal": "1000.00"},
    )

    response = client.patch(
        f"/deliveries/{delivery['id']}", headers=admin_a, json={"scheduled_at": _tomorrow()}
    )
    assert response.status_code == 409


def test_drivers_cannot_reassign(client, admin_a, driver_a):
    delivery = _scheduled_delivery(client, admin_a)
    response = client.patch(
        f"/deliveries/{delivery['id']}", headers=driver_a, json={"driver_id": None}
    )
    assert response.status_code == 403


def test_cannot_reschedule_another_tenants_delivery(client, admin_a, admin_b):
    delivery = _scheduled_delivery(client, admin_b)
    response = client.patch(
        f"/deliveries/{delivery['id']}", headers=admin_a, json={"scheduled_at": _tomorrow()}
    )
    assert response.status_code == 404


# ---------- adding a customer mid-order ----------

def test_creating_a_customer_and_site(client, admin_a, tenant_a):
    created = client.post(
        "/customers",
        headers=admin_a,
        json={"name": "Bayou Haulage", "payment_terms_days": 30},
    )
    assert created.status_code == 201, created.text
    customer_id = created.json()["id"]

    site = client.post(
        "/sites",
        headers=admin_a,
        json={
            "customer_id": customer_id,
            "address": "4100 Navigation Blvd",
            "tank_capacity_gal": "6000.00",
        },
    )
    assert site.status_code == 201, site.text

    with Session(admin_engine) as session:
        stored = session.get(DeliverySite, uuid.UUID(site.json()["id"]))
        # The tenant comes from the token, never the payload.
        assert stored.tenant_id == tenant_a.id


def test_cannot_attach_a_site_to_another_tenants_customer(
    client, admin_a, customer_id_b
):
    """A real customer id, guessed correctly, still fails: the lookup runs
    under the policy, so it is not visible to this tenant."""
    response = client.post(
        "/sites",
        headers=admin_a,
        json={
            "customer_id": str(customer_id_b),
            "address": "Somewhere else entirely",
            "tank_capacity_gal": "1000.00",
        },
    )
    assert response.status_code == 404


def test_drivers_cannot_create_customers(client, driver_a):
    response = client.post(
        "/customers", headers=driver_a, json={"name": "Nope", "payment_terms_days": 30}
    )
    assert response.status_code == 403
