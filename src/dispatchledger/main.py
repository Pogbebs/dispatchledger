"""The FastAPI application."""

from fastapi import FastAPI

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
    return {"status": "ok"}
