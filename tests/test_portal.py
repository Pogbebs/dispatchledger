"""The customer portal.

The isolation claim here is narrower than anywhere else in the project, and
therefore easier to get wrong. Tenant isolation separates two companies that
never share a row. Customer isolation separates two customers of the *same*
company, whose rows sit in the same tables with the same tenant_id, told apart
only by a restrictive policy on one database role.

So these tests ask the same question twice: can a customer reach another
customer's data through an endpoint, and can the portal role reach it through
SQL at all.
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from dispatchledger.db import admin_engine, portal_engine
from dispatchledger.models import DeliverySite, Invoice, Order


def _tomorrow() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


def _orders(client, headers) -> list[dict]:
    response = client.get("/portal/orders", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---------- the database layer ----------

def test_portal_role_sees_nothing_without_a_customer():
    """The guarantee underneath everything else.

    Connect as dispatch_portal, set neither the tenant nor the customer, and
    ask for orders. NULL matches no row, so the honest answer is zero. A
    number other than zero here means the restrictive policy is missing or the
    role has acquired a way around it, and every test below would still pass
    while the system leaked.
    """
    with Session(portal_engine) as session:
        for table in ("orders", "invoices", "deliveries", "customers", "delivery_sites"):
            visible = session.execute(text(f"SELECT count(*) FROM {table}")).scalar()
            assert visible == 0, f"{table} leaked {visible} rows to an unscoped portal role"


def test_portal_role_sees_nothing_with_a_tenant_but_no_customer(tenant_a):
    """Half-scoped is not partly scoped.

    Setting the tenant alone is what a bug would most plausibly do -- copying
    the staff session and forgetting the second line. The restrictive policy
    is ANDed, so it still matches nothing. If this returned the tenant's rows,
    one missed SET LOCAL would hand a customer their competitors' orders.
    """
    with Session(portal_engine) as session:
        session.execute(
            text("SELECT set_config('app.current_tenant', :t, false)"),
            {"t": str(tenant_a.id)},
        )
        visible = session.execute(text("SELECT count(*) FROM orders")).scalar()
        assert visible == 0


def test_portal_role_cannot_read_the_marts():
    """No grant at all on the warehouse.

    The Insights mart holds margin against benchmark for every tenant. The
    portal role has no SELECT on it, so this is a permission error rather than
    an empty result -- a stronger statement than a policy returning no rows.
    """
    # The warehouse is built by dbt, not by migrations, so a database that has
    # only had `alembic upgrade head` run against it has no marts at all.
    #
    # Asked on the admin connection deliberately: to_regclass returns NULL for
    # a table the caller cannot see as well as for one that does not exist, so
    # asking as the portal role would skip this test every time -- including
    # when it is the only thing standing between a customer and every tenant's
    # margins.
    with Session(admin_engine) as probe:
        exists = probe.execute(
            text("SELECT to_regclass('analytics_marts.agg_weekly_price_position')")
        ).scalar()
    if exists is None:
        pytest.skip("Marts not built here; run dbt build first.")

    with Session(portal_engine) as session:
        with pytest.raises(Exception) as caught:
            session.execute(
                text("SELECT count(*) FROM analytics_marts.agg_weekly_price_position")
            )
        assert "permission denied" in str(caught.value).lower()


# ---------- what a customer can see ----------

def _ids_in_tenant(model, tenant_id, customer_id) -> tuple[set[str], set[str]]:
    """Every id in this tenant, split into this customer's and everyone else's.

    Read from the database rather than from a staff endpoint. The endpoints
    page at 200 rows and the seeded tenant has more than that, so a page is
    not the tenant -- a subset check against one would fail for a customer
    whose orders happen to sit past the cut. That is a property of the test,
    not of the thing under test, and it has caught this suite out before.
    """
    with Session(admin_engine) as session:
        rows = session.execute(
            select(model.id, model.customer_id).where(model.tenant_id == tenant_id)
        ).all()
    mine = {str(i) for i, owner in rows if str(owner) == str(customer_id)}
    others = {str(i) for i, owner in rows if str(owner) != str(customer_id)}
    return mine, others


def test_customer_sees_only_their_own_orders(
    client, customer_a, tenant_a, customer_a_id
):
    """Every order the portal returns is theirs, and none of anyone else's."""
    visible = {row["id"] for row in _orders(client, customer_a)}
    theirs, others = _ids_in_tenant(Order, tenant_a.id, customer_a_id)

    assert visible, "the seeded portal customer should have orders"
    assert others, "the tenant should have other customers to be isolated from"
    assert visible.isdisjoint(others)
    assert visible <= theirs


def test_customer_sees_only_their_own_invoices(client, customer_a, tenant_a, customer_a_id):
    visible = {r["id"] for r in client.get("/portal/invoices", headers=customer_a).json()}
    theirs, others = _ids_in_tenant(Invoice, tenant_a.id, customer_a_id)

    assert visible
    assert others
    assert visible.isdisjoint(others)
    assert visible <= theirs


def test_customer_sees_only_their_own_sites(client, customer_a, tenant_a, customer_a_id):
    visible = {s["id"] for s in client.get("/portal/sites", headers=customer_a).json()}
    theirs, others = _ids_in_tenant(DeliverySite, tenant_a.id, customer_a_id)

    # Equality, not a subset: a customer should see all of their own sites,
    # or the order form would silently omit somewhere they can take fuel.
    assert visible == theirs
    assert visible.isdisjoint(others)


def test_two_tenants_customers_are_still_isolated(client, customer_a, customer_b):
    """The original guarantee, still holding underneath the new one."""
    a = {row["id"] for row in _orders(client, customer_a)}
    b = {row["id"] for row in _orders(client, customer_b)}
    assert a and b
    assert a.isdisjoint(b)


def test_me_names_the_customer(client, customer_a):
    body = client.get("/me", headers=customer_a).json()
    assert body["role"] == "customer"
    assert body["customer_id"]
    assert body["customer_name"]
    # The distributor is named too: a customer should know who supplies them.
    assert body["tenant_name"]


# ---------- the two directions of the role boundary ----------

@pytest.mark.parametrize(
    "path",
    ["/orders", "/deliveries", "/customers", "/invoices", "/insights", "/drivers"],
)
def test_customer_cannot_reach_staff_endpoints(client, customer_a, path):
    """Refused in the shared session dependency, not endpoint by endpoint.

    These are read-only staff routes with no role guard of their own. Before
    the portal existed there was nothing to guard against; a customer token
    would have run them on the staff connection and listed the whole tenant.
    """
    response = client.get(path, headers=customer_a)
    assert response.status_code == 403, f"{path} returned {response.status_code}"


@pytest.mark.parametrize(
    "path", ["/portal/overview", "/portal/orders", "/portal/invoices", "/portal/sites"]
)
def test_staff_cannot_reach_portal_endpoints(client, admin_a, path):
    """Not a security boundary so much as an honesty one.

    An admin reaching these would get an empty page, because their token
    carries no customer. Refusing says so instead of implying the customer has
    no orders.
    """
    assert client.get(path, headers=admin_a).status_code == 403


def test_portal_requires_authentication(client):
    assert client.get("/portal/orders").status_code == 401


def test_customer_cannot_pay_their_own_invoice(client, customer_a, admin_a):
    """The capability does not exist for them at any layer.

    The endpoint requires a staff role, and the portal role has no UPDATE
    grant on invoices either -- so even a forged route would fail in the
    database.
    """
    unpaid = [
        r
        for r in client.get("/invoices?limit=200&status=unpaid", headers=admin_a).json()["rows"]
    ]
    if not unpaid:
        pytest.skip("No unpaid invoices seeded.")
    response = client.post(f"/invoices/{unpaid[0]['id']}/pay", headers=customer_a)
    assert response.status_code == 403


# ---------- placing an order ----------

def test_placing_an_order_takes_the_customer_from_the_token(
    client, customer_a, customer_a_id
):
    sites = client.get("/portal/sites", headers=customer_a).json()
    products = client.get("/portal/products", headers=customer_a).json()
    assert sites and products

    response = client.post(
        "/portal/orders",
        headers=customer_a,
        json={
            "site_id": sites[0]["id"],
            "product_id": products[0]["id"],
            "quantity_gal": "1200.00",
            "requested_date": _tomorrow(),
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["customer_id"] == customer_a_id
    assert body["status"] == "pending"
    # Priced from the catalogue, not from anything the client sent.
    assert float(body["unit_price"]) > 0


def test_cannot_order_against_another_customers_site(client, customer_a, admin_a, customer_a_id):
    """A real site id, belonging to someone else at the same distributor.

    404 rather than 403: under the policy that row is not there to be refused.
    """
    others = [
        s
        for s in client.get("/sites", headers=admin_a).json()
        if s["customer_id"] != customer_a_id
    ]
    if not others:
        pytest.skip("Tenant has only one customer with sites.")

    products = client.get("/portal/products", headers=customer_a).json()
    response = client.post(
        "/portal/orders",
        headers=customer_a,
        json={
            "site_id": others[0]["id"],
            "product_id": products[0]["id"],
            "quantity_gal": "500.00",
            "requested_date": _tomorrow(),
        },
    )
    assert response.status_code == 404


def test_a_customer_id_in_the_body_is_ignored(client, customer_a, customer_a_id, customer_id_b):
    """There is no field for it, so an extra key changes nothing.

    Pydantic drops what the schema does not declare. Worth asserting because
    "the server ignores it" is a claim, and a schema gaining a field later
    would quietly make it false.
    """
    sites = client.get("/portal/sites", headers=customer_a).json()
    products = client.get("/portal/products", headers=customer_a).json()

    response = client.post(
        "/portal/orders",
        headers=customer_a,
        json={
            "site_id": sites[0]["id"],
            "product_id": products[0]["id"],
            "quantity_gal": "750.00",
            "requested_date": _tomorrow(),
            "customer_id": str(customer_id_b),
            "tenant_id": str(uuid.uuid4()),
            "unit_price": "0.01",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["customer_id"] == customer_a_id
    assert float(response.json()["unit_price"]) > 0.01


def test_cannot_order_in_the_past(client, customer_a):
    sites = client.get("/portal/sites", headers=customer_a).json()
    products = client.get("/portal/products", headers=customer_a).json()
    response = client.post(
        "/portal/orders",
        headers=customer_a,
        json={
            "site_id": sites[0]["id"],
            "product_id": products[0]["id"],
            "quantity_gal": "500.00",
            "requested_date": (date.today() - timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 422


# ---------- cancelling ----------

def _fresh_order(client, headers) -> str:
    sites = client.get("/portal/sites", headers=headers).json()
    products = client.get("/portal/products", headers=headers).json()
    return client.post(
        "/portal/orders",
        headers=headers,
        json={
            "site_id": sites[0]["id"],
            "product_id": products[0]["id"],
            "quantity_gal": "900.00",
            "requested_date": _tomorrow(),
        },
    ).json()["id"]


def test_customer_can_cancel_their_own_pending_order(client, customer_a):
    order_id = _fresh_order(client, customer_a)
    response = client.post(f"/portal/orders/{order_id}/cancel", headers=customer_a)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"


def test_customer_cannot_cancel_a_scheduled_order(client, customer_a, admin_a):
    """Once a run is on the board it is the dispatcher's to move."""
    order_id = _fresh_order(client, customer_a)
    scheduled = client.post(
        "/deliveries",
        headers=admin_a,
        json={
            "order_id": order_id,
            "scheduled_at": f"{_tomorrow()}T08:00:00Z",
        },
    )
    assert scheduled.status_code == 201, scheduled.text

    response = client.post(f"/portal/orders/{order_id}/cancel", headers=customer_a)
    assert response.status_code == 409


def test_cannot_cancel_another_tenants_order(client, customer_a, order_id_b):
    response = client.post(f"/portal/orders/{order_id_b}/cancel", headers=customer_a)
    assert response.status_code == 404


# ---------- invitations ----------

def test_inviting_and_accepting(client, admin_a):
    """The whole provisioning path: invite, accept, sign in, see your own rows."""
    customers = client.get("/customers?limit=200", headers=admin_a).json()
    # Pick a customer that has no portal account yet.
    target = customers[-1]
    email = f"portal-test-{uuid.uuid4().hex[:8]}@example.com"

    created = client.post(
        "/invites",
        headers=admin_a,
        json={"customer_id": target["id"], "email": email, "full_name": "Test Contact"},
    )
    assert created.status_code == 201, created.text
    accept_path = created.json()["accept_path"]
    token = accept_path.rsplit("/", 1)[-1]

    accepted = client.post(
        "/invites/accept", json={"token": token, "password": "aSufficientlyLong1"}
    )
    assert accepted.status_code == 201, accepted.text
    headers = {"Authorization": f"Bearer {accepted.json()['access_token']}"}

    me = client.get("/me", headers=headers).json()
    assert me["role"] == "customer"
    assert me["customer_id"] == target["id"]

    # And the new account is scoped like any other.
    assert client.get("/orders", headers=headers).status_code == 403


def test_an_invitation_works_only_once(client, admin_a):
    customers = client.get("/customers?limit=200", headers=admin_a).json()
    email = f"portal-once-{uuid.uuid4().hex[:8]}@example.com"
    created = client.post(
        "/invites",
        headers=admin_a,
        json={"customer_id": customers[0]["id"], "email": email, "full_name": "Once"},
    )
    token = created.json()["accept_path"].rsplit("/", 1)[-1]

    first = client.post("/invites/accept", json={"token": token, "password": "aSufficientlyLong1"})
    assert first.status_code == 201

    again = client.post("/invites/accept", json={"token": token, "password": "aSufficientlyLong2"})
    assert again.status_code == 400


def test_an_unknown_token_is_refused_like_a_used_one(client):
    """Same status, same message: a probe cannot tell live tokens from dead."""
    response = client.post(
        "/invites/accept",
        json={"token": "x" * 43, "password": "aSufficientlyLong1"},
    )
    assert response.status_code == 400


def test_drivers_cannot_invite(client, driver_a, admin_a):
    customers = client.get("/customers?limit=200", headers=admin_a).json()
    response = client.post(
        "/invites",
        headers=driver_a,
        json={
            "customer_id": customers[0]["id"],
            "email": "nope@example.com",
            "full_name": "Nope",
        },
    )
    assert response.status_code == 403


def test_cannot_invite_against_another_tenants_customer(client, admin_a, customer_id_b):
    response = client.post(
        "/invites",
        headers=admin_a,
        json={
            "customer_id": str(customer_id_b),
            "email": f"cross-{uuid.uuid4().hex[:8]}@example.com",
            "full_name": "Cross Tenant",
        },
    )
    assert response.status_code == 404


def test_invite_list_never_carries_a_token(client, admin_a):
    """Only the hash was stored, so there is nothing to leak -- asserted so a
    future convenience field cannot quietly reintroduce one."""
    for invite in client.get("/invites", headers=admin_a).json():
        assert "token" not in invite
        assert "accept_path" not in invite
