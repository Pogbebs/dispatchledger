"""The health endpoint, which a hosting platform uses to decide about restarts.

Worth testing precisely because it looks trivial. A check that returns 200
unconditionally passes any test asserting 200, keeps a broken instance in the
load balancer, and nothing ever says otherwise.
"""

from unittest.mock import patch

from sqlalchemy.exc import OperationalError


def test_health_is_ok_when_the_database_is_reachable(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_needs_no_authentication(client):
    """The platform calling it has no token, so a 401 here would read as down."""
    assert client.get("/health").status_code == 200


def test_health_fails_when_the_database_is_unreachable(client):
    """The check has to be capable of failing, or it is decoration.

    Simulated rather than achieved by stopping Postgres, so the suite stays
    runnable in one command -- but it does exercise the real code path: the
    connection raises, and the endpoint has to turn that into a 503 rather
    than a 500 or an unhandled traceback.
    """
    with patch("dispatchledger.main.app_engine") as engine:
        engine.connect.side_effect = OperationalError("SELECT 1", {}, Exception("down"))

        response = client.get("/health")

    assert response.status_code == 503
    assert "database unreachable" in response.json()["detail"]
    # The message names which connection failed and nothing else: no host, no
    # driver error, no connection string. It is an unauthenticated endpoint.
    assert "localhost" not in response.text
    assert "password" not in response.text.lower()
