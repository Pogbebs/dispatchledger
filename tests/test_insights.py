"""The Insights endpoint, which reads the warehouse instead of the app tables.

These are the tests that matter most for that endpoint, because it is the one
place the application touches a schema owned by the analytics role. If the
row-security policy dbt attaches to the mart were ever dropped -- or silently
lost when dbt recreated the table -- the isolation tests below are what would
notice.

They skip rather than fail when the warehouse has not been built: the app
schema comes from Alembic and the marts from dbt, and a database with one and
not the other is a normal state to run the suite in.
"""

import pytest


def _insights(client, headers, weeks: int = 52) -> dict:
    response = client.get(f"/insights?weeks={weeks}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _require_warehouse(payload: dict) -> dict:
    if not payload["warehouse_available"]:
        pytest.skip("Run `dbt build` in analytics/: these tests need the marts.")
    if not payload["weeks"]:
        pytest.skip("Warehouse built but holds no benchmarked deliveries.")
    return payload


def test_requires_authentication(client):
    assert client.get("/insights").status_code == 401


def test_reports_whether_the_warehouse_exists(client, admin_a):
    """A missing warehouse is answered, not raised.

    The UI can explain 'not built yet'. It cannot explain a 500.
    """
    payload = _insights(client, admin_a)
    assert isinstance(payload["warehouse_available"], bool)


def test_each_tenant_sees_only_its_own_weeks(client, admin_a, admin_b):
    """The mart holds both tenants. Each token must reach exactly one.

    There is no tenant filter in the handler's SQL -- the policy dbt attaches
    to the table is the only thing separating these two responses.
    """
    a = _require_warehouse(_insights(client, admin_a))
    b = _insights(client, admin_b)

    if not b["weeks"]:
        pytest.skip("Second tenant has no benchmarked deliveries to compare.")

    # Same weeks, different money: proof the rows are genuinely distinct
    # rather than one tenant simply seeing nothing.
    assert a["summary"]["delivered_gal"] != b["summary"]["delivered_gal"]


def test_window_bounds_the_result(client, admin_a):
    payload = _require_warehouse(_insights(client, admin_a, weeks=4))
    assert len(payload["weeks"]) <= 4
    assert payload["summary"]["weeks_covered"] == len(payload["weeks"])


def test_weeks_are_chronological(client, admin_a):
    """The chart reads left to right, so the API hands them over in that order."""
    payload = _require_warehouse(_insights(client, admin_a))
    weeks = [w["week_start"] for w in payload["weeks"]]
    assert weeks == sorted(weeks)


def test_summary_matches_the_window_it_describes(client, admin_a):
    """A headline computed over more data than the chart shows is a lie.

    Also checks the weighting: the summary must divide summed revenue by
    summed gallons, not average the weekly averages.
    """
    payload = _require_warehouse(_insights(client, admin_a, weeks=8))
    weeks = payload["weeks"]
    summary = payload["summary"]

    assert summary["first_week"] == weeks[0]["week_start"]
    assert summary["latest_week"] == weeks[-1]["week_start"]
    assert summary["delivery_count"] == sum(w["delivery_count"] for w in weeks)

    gallons = sum(float(w["delivered_gal"]) for w in weeks)
    revenue = sum(float(w["revenue"]) for w in weeks)
    assert float(summary["avg_price"]) == pytest.approx(revenue / gallons, abs=1e-4)


def test_delta_is_the_difference_between_the_two_prices(client, admin_a):
    """The number on screen has to be the subtraction it claims to be.

    Tolerance is two mils, not zero: all three figures are rounded to four
    places independently in the warehouse, so the subtraction can legitimately
    land one unit off in the last digit. Asserting exact equality here would
    produce a test that fails on arithmetic rather than on a defect.
    """
    payload = _require_warehouse(_insights(client, admin_a))
    for week in payload["weeks"]:
        expected = float(week["avg_price"]) - float(week["market_price"])
        assert float(week["price_delta"]) == pytest.approx(expected, abs=2e-4)


def test_drivers_can_read_insights(client, tenant_a):
    """Read-only reporting is not restricted by role; writes still are."""
    token = client.post(
        "/login",
        json={
            "tenant_slug": tenant_a.slug,
            "email": f"driver1@{tenant_a.slug}.example.com",
            "password": "demo1234",
        },
    ).json()["access_token"]

    response = client.get("/insights", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
