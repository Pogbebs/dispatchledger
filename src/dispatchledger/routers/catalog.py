"""Read-only catalog: the products and delivery sites an order can reference."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from dispatchledger.deps import get_session
from dispatchledger.models import DeliverySite, Product
from dispatchledger.schemas import ProductOut, SiteOut

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
