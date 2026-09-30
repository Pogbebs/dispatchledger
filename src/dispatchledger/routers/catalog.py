"""The products, sites and drivers an order or delivery can reference."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from dispatchledger.deps import CurrentUser, get_session, require_role
from dispatchledger.models import DeliverySite, Product, User
from dispatchledger.schemas import DriverOut, ProductOut, SiteCreate, SiteOut

router = APIRouter(tags=["catalog"])


@router.get("/products", response_model=list[ProductOut])
def list_products(session: Session = Depends(get_session)) -> list[Product]:
    return list(session.scalars(select(Product).order_by(Product.name)))


@router.get("/sites", response_model=list[SiteOut])
def list_sites(
    session: Session = Depends(get_session),
    customer_id: uuid.UUID | None = Query(default=None),
) -> list[DeliverySite]:
    stmt = select(DeliverySite).order_by(DeliverySite.address)
    if customer_id is not None:
        stmt = stmt.where(DeliverySite.customer_id == customer_id)
    return list(session.scalars(stmt))


@router.get("/drivers", response_model=list[DriverOut])
def list_drivers(session: Session = Depends(get_session)) -> list[User]:
    """Drivers who can be assigned a delivery.

    Returns id and name only. A scheduling dropdown has no use for email
    addresses, and an endpoint that hands out a staff directory to anyone
    signed in is a larger promise than this screen needs.
    """
    stmt = select(User).where(User.role == "driver").order_by(User.full_name)
    return list(session.scalars(stmt))


@router.post("/sites", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
def create_site(
    payload: SiteCreate,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_role("admin", "dispatcher")),
) -> DeliverySite:
    """A new tank at a customer location.

    The customer is looked up first rather than trusted from the payload: the
    row-security policy means a customer_id belonging to another tenant
    returns nothing here, so this cannot attach a site to someone else's
    customer even if the id is real and guessed correctly.
    """
    from dispatchledger.models import Customer

    if session.get(Customer, payload.customer_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")

    site = DeliverySite(tenant_id=user.tenant_id, **payload.model_dump())
    session.add(site)
    session.flush()
    return site
