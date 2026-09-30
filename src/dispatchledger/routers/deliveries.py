"""Deliveries. Completing one bills the customer for what actually arrived."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dispatchledger.deps import CurrentUser, get_session, require_role
from dispatchledger.models import Customer, Delivery, Invoice, Order, Product, User
from dispatchledger.schemas import (
    DeliveryComplete,
    DeliveryCreate,
    DeliveryOut,
    DeliveryReschedule,
    DeliveryRow,
)

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


def _validated_driver(session: Session, driver_id: uuid.UUID | None) -> uuid.UUID | None:
    """Confirm a driver id refers to a driver in this tenant.

    Two checks, for two different mistakes. The lookup runs under the
    row-security policy, so another tenant's user returns None and cannot be
    assigned a delivery -- the id being real is not enough. The role check
    stops an admin or dispatcher being put on a run, which the schema allows
    (driver_id is just a user id) and the business does not.
    """
    if driver_id is None:
        return None

    driver = session.get(User, driver_id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Driver not found")
    if driver.role != "driver":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{driver.full_name} is a {driver.role}, not a driver",
        )
    return driver.id


@router.get("", response_model=list[DeliveryRow])
def list_deliveries(
    session: Session = Depends(get_session),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """Rows carry the order's customer, product and ordered quantity.

    The ordered quantity matters on this screen: a driver completing a
    delivery needs to see what was asked for before recording what arrived.
    """
    stmt = (
        select(Delivery, Customer.name, Product.name, Order.quantity_gal, User.full_name)
        .join(Order, Order.id == Delivery.order_id)
        .join(Customer, Customer.id == Order.customer_id)
        .join(Product, Product.id == Order.product_id)
        .outerjoin(User, User.id == Delivery.driver_id)
        .order_by(Delivery.scheduled_at.desc())
    )
    if status_filter:
        stmt = stmt.where(Delivery.status == status_filter)

    return [
        {
            **{c.name: getattr(delivery, c.name) for c in Delivery.__table__.columns},
            "customer_name": customer_name,
            "product_name": product_name,
            "ordered_gal": ordered_gal,
            "driver_name": driver_name,
        }
        for delivery, customer_name, product_name, ordered_gal, driver_name in (
            session.execute(stmt.limit(limit).offset(offset))
        )
    ]


@router.post("", response_model=DeliveryOut, status_code=status.HTTP_201_CREATED)
def schedule_delivery(
    payload: DeliveryCreate,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_role("admin", "dispatcher")),
) -> Delivery:
    """Dispatchers schedule. Drivers do not."""
    order = session.get(Order, payload.order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if order.status == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Order is cancelled")

    delivery = Delivery(
        tenant_id=user.tenant_id,
        order_id=order.id,
        driver_id=_validated_driver(session, payload.driver_id),
        scheduled_at=payload.scheduled_at,
        status="scheduled",
    )
    order.status = "scheduled"
    session.add(delivery)
    session.flush()
    return delivery


@router.post("/{delivery_id}/complete", response_model=DeliveryOut)
def complete_delivery(
    delivery_id: uuid.UUID,
    payload: DeliveryComplete,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_role("admin", "dispatcher", "driver")),
) -> Delivery:
    """Record what was actually delivered, then invoice for that amount."""
    delivery = session.get(Delivery, delivery_id)
    if delivery is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Delivery not found")
    if delivery.status == "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Delivery already completed")

    # A driver may only close out their own delivery.
    if user.role == "driver" and delivery.driver_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your delivery")

    order = session.get(Order, delivery.order_id)
    customer = session.get(Customer, order.customer_id)

    delivered_at = payload.delivered_at or datetime.now(timezone.utc)
    delivery.delivered_gal = payload.delivered_gal
    delivery.delivered_at = delivered_at
    delivery.status = "completed"
    order.status = "delivered"

    # Billed on delivered gallons, not ordered gallons, at the price the
    # order locked in.
    amount = (payload.delivered_gal * order.unit_price).quantize(Decimal("0.01"))
    issued = delivered_at.date()

    # Per-tenant sequence. Under RLS the count only sees this tenant's rows,
    # and the (tenant_id, invoice_number) unique constraint is the real guard
    # against a duplicate if two completions race.
    used = session.scalar(select(func.count()).select_from(Invoice)) or 0
    session.add(
        Invoice(
            tenant_id=user.tenant_id,
            customer_id=customer.id,
            delivery_id=delivery.id,
            invoice_number=f"INV-{1001 + used}",
            issued_at=issued,
            due_date=issued + timedelta(days=customer.payment_terms_days),
            amount=amount,
            status="unpaid",
        )
    )
    session.flush()
    return delivery


@router.patch("/{delivery_id}", response_model=DeliveryOut)
def reschedule_delivery(
    delivery_id: uuid.UUID,
    payload: DeliveryReschedule,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_role("admin", "dispatcher")),
) -> Delivery:
    """Change the driver or the date on a delivery that has not happened yet.

    Trucks break down and people call in sick, so a schedule that cannot be
    changed is a schedule that gets kept in a spreadsheet instead.

    Only dispatchers and admins: a driver reassigning their own run to someone
    else is not a workflow, it is an argument.
    """
    delivery = session.get(Delivery, delivery_id)
    if delivery is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Delivery not found")
    if delivery.status == "completed":
        # The invoice is already written against it. Changing who delivered
        # or when, after the fact, would put the billing record and the
        # delivery record into disagreement.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Delivery is completed and cannot be rescheduled",
        )

    supplied = payload.model_fields_set
    if not supplied:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to change")

    # An explicit null unassigns the driver, which is different from the field
    # being absent -- hence model_fields_set rather than a None check.
    if "driver_id" in supplied:
        delivery.driver_id = _validated_driver(session, payload.driver_id)
    if "scheduled_at" in supplied and payload.scheduled_at is not None:
        delivery.scheduled_at = payload.scheduled_at

    session.flush()
    return delivery
