"""The FastAPI application."""

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from dispatchledger.config import REPO_ROOT
from dispatchledger.db import admin_engine, app_engine
from dispatchledger.routers import auth, catalog, customers, deliveries, insights, orders

app = FastAPI(
    title="DispatchLedger",
    version="0.1.0",
    description=(
        "Multi-tenant operations platform for fuel distributors. Tenant "
        "isolation is enforced by Postgres row-level security, not by "
        "filters in application code."
    ),
)

app.include_router(auth.router)
app.include_router(customers.router)
app.include_router(orders.router)
app.include_router(deliveries.router)
app.include_router(catalog.router)
app.include_router(insights.router)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Liveness, including the database.

    A check that only proves the process is running will report a perfectly
    healthy instance that cannot serve a single request. Hosting platforms
    restart on a failing health check, and they can only do that if the check
    is capable of failing.

    Both engines are tried because both are on the request path: every
    handler uses the application role, and the login endpoint uses the owner
    role to find a tenant before any tenant is known. Either being down means
    the service is not usable, so either failing means unhealthy.
    """
    for name, engine in (("app", app_engine), ("admin", admin_engine)):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            # The reason is in the server log; the response says only which
            # connection failed. A health endpoint is unauthenticated, so it
            # is not the place to publish a connection string or a driver
            # error naming the host.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"database unreachable ({name})",
            ) from None

    return {"status": "ok"}


# --- the built web app ------------------------------------------------------
#
# Serving the React build from the API means one service rather than two, and
# no CORS at all: the browser sees a single origin, exactly as it does behind
# the Vite dev proxy locally. Two services would need a CORS allowlist that has
# to be kept in step with wherever the frontend happens to be deployed.
#
# Mounted only when a build exists, so development and CI -- where web/dist is
# absent -- behave exactly as before.

WEB_DIST = REPO_ROOT / "web" / "dist"

if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str) -> FileResponse:
        """Hand any unmatched path to the client-side router.

        React Router owns /orders, /insights and the rest; they are not files
        on disk. Returning 404 for them would break every bookmark and every
        page refresh. Registered last, so real API routes always win.
        """
        candidate = WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
