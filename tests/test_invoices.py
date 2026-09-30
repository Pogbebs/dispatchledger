"""Invoices -- the receivables side, which had no API until now.

The isolation tests here matter more than usual. An invoice names a customer
and an amount; a leak between tenants would expose two competing distributors'
pricing to each other, which is the exact scenario this project exists to make
impossible.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from dispatchledger.db import admin_engine
from dispatchledger.models import Invoice


# The page size the web app asks for. Stated here rather than relying on the
# endpoint's default, because a test that silently depends on a default is a
# test that breaks when the default changes for an unrelated reason -- which
# is exactly how this one first failed.
PAGE_SIZE = 200


def _invoices(client, headers, status: str | None = None) -> dict:
    query = f"?limit={PAGE_SIZE}" + (f"&status={status}" if status else "")
    response = client.get(f"/invoices{query}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _unpaid_id(client, headers) -> str:
    rows = _invoices(client, headers, "unpaid")["rows"]
    if not rows:
        pytest.skip("No unpaid invoices in the seeded data.")
    return rows[0]["id"]


def test_requires_authentication(client):
    assert client.get("/invoices").status_code == 401


def test_each_tenant_sees_only_its_own_invoices(client, admin_a, admin_b):
    a = {r["invoice_number"] for r in _invoices(client, admin_a)["rows"]}
    b = {r["invoice_number"] for r in _invoices(client, admin_b)["rows"]}

    assert a and b
    # Invoice numbers are per-tenant sequences, so the two sets overlap by
    # design -- INV-1001 exists for both. Comparing ids is the real check.
    ids_a = {r["id"] for r in _invoices(client, admin_a)["rows"]}
    ids_b = {r["id"] for r in _invoices(client, admin_b)["rows"]}
    assert ids_a.isdisjoint(ids_b)


def test_listing_is_not_merely_empty(client, admin_a, tenant_a):
    """Guards against the opposite bug: a policy so tight nobody sees anything."""
    returned = len(_invoices(client, admin_a)["rows"])
    with Session(admin_engine) as session:
        total = len(
            list(session.scalars(select(Invoice.id).where(Invoice.tenant_id == tenant_a.id)))
        )
    assert returned == min(total, PAGE_SIZE)


def test_summary_covers_every_invoice_not_the_filter(client, admin_a):
    """What you are owed is a fact about the business, not about the filter.

    A summary that changed as you clicked between statuses would be a headline
    that disagrees with itself.
    """
    everything = _invoices(client, admin_a)["summary"]
    filtered = _invoices(client, admin_a, "paid")["summary"]
    assert everything == filtered


def test_summary_arithmetic_holds(client, admin_a):
    summary = _invoices(client, admin_a)["summary"]

    # Overdue is a subset of outstanding, never larger.
    assert summary["overdue_count"] <= summary["outstanding_count"]
    assert float(summary["overdue_total"]) <= float(summary["outstanding_total"])

    unpaid_rows = _invoices(client, admin_a, "unpaid")["rows"]
    assert summary["outstanding_count"] == len(unpaid_rows)
    assert float(summary["outstanding_total"]) == pytest.approx(
        sum(float(r["amount"]) for r in unpaid_rows), abs=0.01
    )


def test_overdue_is_computed_from_the_due_date(client, admin_a):
    today = date.today()
    for row in _invoices(client, admin_a)["rows"]:
        due = date.fromisoformat(row["due_date"])
        if row["status"] == "unpaid" and due < today:
            assert row["days_overdue"] == (today - due).days
        else:
            # A paid invoice settled late is not currently overdue. Counting
            # it would overstate receivables.
            assert row["days_overdue"] == 0


def test_marking_paid(client, admin_a):
    invoice_id = _unpaid_id(client, admin_a)

    response = client.post(f"/invoices/{invoice_id}/pay", headers=admin_a)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "paid"
    assert body["paid_at"] is not None
    assert body["days_overdue"] == 0


def test_paying_twice_is_a_conflict(client, admin_a):
    invoice_id = _unpaid_id(client, admin_a)
    client.post(f"/invoices/{invoice_id}/pay", headers=admin_a)

    again = client.post(f"/invoices/{invoice_id}/pay", headers=admin_a)
    assert again.status_code == 409


def test_drivers_cannot_record_payment(client, admin_a, driver_a):
    """Drivers deliver fuel, not receivables."""
    invoice_id = _unpaid_id(client, admin_a)
    response = client.post(f"/invoices/{invoice_id}/pay", headers=driver_a)
    assert response.status_code == 403


def test_cannot_pay_another_tenants_invoice(client, admin_a, admin_b):
    """The id is real and the invoice is unpaid. From the wrong tenant it must
    look absent -- 404, not 403, so the response does not confirm it exists."""
    other = _unpaid_id(client, admin_b)
    response = client.post(f"/invoices/{other}/pay", headers=admin_a)
    assert response.status_code == 404


def test_unknown_invoice_is_404(client, admin_a):
    response = client.post(f"/invoices/{uuid.uuid4()}/pay", headers=admin_a)
    assert response.status_code == 404


def test_rows_carry_the_customer_name(client, admin_a):
    """The screen shows who owes the money, so the join happens server-side
    rather than the browser fetching every customer to render one table."""
    rows = _invoices(client, admin_a)["rows"]
    assert rows
    assert all(r["customer_name"] for r in rows)
