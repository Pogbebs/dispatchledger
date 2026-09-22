"""Orders. Price is snapshotted at creation, never looked up later."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from dispatchledger.deps import CurrentUser, get_session, require_role
from dispatchledger.models import Customer, DeliverySite, Order, Product
from dispatchledger.schemas import OrderCreate, OrderOut, OrderRow

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=list[OrderRow])
def list_orders(
    session: Session = Depends(get_session),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """Rows carry customer and product names so one table needs one request."""
    stmt = (
        select(Order, Customer.name, Product.name, DeliverySite.address)
        .join(Customer, Customer.id == Order.customer_id)
        .join(Product, Product.id == Order.product_id)
        .join(DeliverySite, DeliverySite.id == Order.site_id)
        .order_by(Order.requested_date.desc())
    )
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)

    return [
        {
            **{c.name: getattr(order, c.name) for c in Order.__table__.columns},
            "customer_name": customer_name,
            "product_name": product_name,
            "site_address": site_address,
        }
        for order, customer_name, product_name, site_address in session.execute(
            stmt.limit(limit).offset(offset)
        )
    ]


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: uuid.UUID, session: Session = Depends(get_session)) -> Order:
    order = session.get(Order, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_role("admin", "dispatcher")),
) -> Order:
    # These lookups are already tenant-scoped by the policy, so a site or
    # product belonging to someone else reads as missing.
    site = session.get(DeliverySite, payload.site_id)
    if site is None or site.customer_id != payload.customer_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown delivery site")

    product = session.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown product")

    order = Order(
        tenant_id=user.tenant_id,
        customer_id=payload.customer_id,
        site_id=payload.site_id,
        product_id=payload.product_id,
        quantity_gal=payload.quantity_gal,
        # Copied, not referenced. If the list price changes tomorrow, this
        # order and its invoice still say what was agreed today.
        unit_price=product.current_price,
        status="pending",
        requested_date=payload.requested_date,
    )
    session.add(order)
    session.flush()
    return order


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_role("admin", "dispatcher")),
) -> Order:
    order = session.get(Order, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if order.status == "delivered":
        raise HTTPException(status.HTTP_409_CONFLICT, "Delivered orders cannot be cancelled")
    order.status = "cancelled"
    session.flush()
    return order
