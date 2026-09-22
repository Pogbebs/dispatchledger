"""Authentication and authorization."""


def test_health_needs_no_token(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_login_returns_a_token(client, tenant_a):
    response = client.post(
        "/login",
        json={
            "tenant_slug": tenant_a.slug,
            "email": f"admin@{tenant_a.slug}.example.com",
            "password": "demo1234",
        },
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


def test_wrong_password_is_rejected(client, tenant_a):
    response = client.post(
        "/login",
        json={
            "tenant_slug": tenant_a.slug,
            "email": f"admin@{tenant_a.slug}.example.com",
            "password": "wrong",
        },
    )
    assert response.status_code == 401


def test_unknown_tenant_and_unknown_user_look_identical(client, tenant_a):
    """The error must not reveal which tenants or accounts exist."""
    unknown_tenant = client.post(
        "/login",
        json={"tenant_slug": "no-such-tenant", "email": "a@b.com", "password": "demo1234"},
    )
    unknown_user = client.post(
        "/login",
        json={
            "tenant_slug": tenant_a.slug,
            "email": "nobody@example.com",
            "password": "demo1234",
        },
    )
    assert unknown_tenant.status_code == unknown_user.status_code == 401
    assert unknown_tenant.json() == unknown_user.json()


def test_no_token_is_unauthorized(client):
    assert client.get("/customers").status_code == 401


def test_garbage_token_is_unauthorized(client):
    response = client.get("/customers", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_me_returns_the_logged_in_user(client, admin_a, tenant_a):
    response = client.get("/me", headers=admin_a)
    assert response.status_code == 200
    assert response.json()["email"] == f"admin@{tenant_a.slug}.example.com"
    assert response.json()["role"] == "admin"


def test_driver_cannot_create_a_customer(client, driver_a):
    response = client.post(
        "/customers",
        headers=driver_a,
        json={"name": "Should Not Exist Ltd"},
    )
    assert response.status_code == 403


def test_admin_can_create_a_customer(client, admin_a):
    response = client.post(
        "/customers",
        headers=admin_a,
        json={"name": "Bayou Freight Co", "payment_terms_days": 45},
    )
    assert response.status_code == 201
    assert response.json()["payment_terms_days"] == 45


def test_invalid_payload_is_rejected(client, admin_a):
    response = client.post("/customers", headers=admin_a, json={"name": ""})
    assert response.status_code == 422
