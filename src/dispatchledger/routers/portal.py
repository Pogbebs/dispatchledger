"""The customer portal.

Everything here runs on ``dispatch_portal``, a login role carrying a
restrictive policy that narrows the tenant policy to one customer. Restrictive
means ANDed: this connection can never see more than a staff connection would,
only less.

What that buys is that none of these handlers filters by customer. There is no
``where customer_id = ...`` below, and adding one would be redundant rather
than protective. A row belonging to another customer of the same distributor
is not hidden from these queries -- it is absent from them.

The deliberate omissions are as interesting as what is here. There is no
endpoint for the driver roster, none for the Insights marts, and none for
marking an invoice paid. A customer settling their own invoice with a click is
the first thing a reviewer looks for.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dispatchledger.deps import CurrentUser, get_current_user, get_portal_session
from dispatchledger.models import (
    Delivery,
    DeliverySite,
    Invoice,
    Order,
    Product,
)
from dispatchledger.schemas import (
    OrderOut,
    PortalInvoiceRow,
    PortalOrderCreate,
    PortalOrderRow,
    PortalOverview,
    PortalSummary,
    ProductOut,
    SiteOut,
)

router = APIRouter(prefix="/portal", tags=["portal"])


def _order_rows(session: Session, limit: int = 200) -> list[dict]:
    """Orders with the delivery attached, newest first.

    An outer join: an order that has not been scheduled yet still belongs on
    the customer's screen, with empty delivery columns. An inner join would
    silently hide exactly the orders they are most likely to be asking about.
    """
    stmt = (
        select(Order, DeliverySite.address, Product.name, Delivery)
        .join(DeliverySite, DeliverySite.id == Order.site_id)
        .join(Product, Product.id == Order.product_id)
        .outerjoin(Delivery, Delivery.order_id == Order.id)
        .order_by(Order.requested_date.desc())
        .limit(limit)
    )

    return [
        {
            "id": order.id,
            "site_address": address,
            "product_name": product_name,
            "quantity_gal": order.quantity_gal,
            "unit_price": order.unit_price,
            "status": order.status,
            "requested_date": order.requested_date,
            "scheduled_at": delivery.scheduled_at if delivery else None,
            "delivered_at": delivery.delivered_at if delivery else None,
            "delivered_gal": delivery.delivered_gal if delivery else None,
        }
        for order, address, product_name, delivery in session.execute(stmt)
    ]


@router.get("/overview", response_model=PortalOverview)
def overview(session: Session = Depends(get_portal_session)) -> dict:
    """The landing screen: where things stand, then the orders themselves.

    One request rather than four. The counts come from the database instead of
    from the returned rows, so a customer with more orders than the page shows
    still sees a correct total.
    """
    open_orders = session.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.status.in_(("pending", "scheduled")))
    )
    scheduled = session.scalar(
        select(func.count()).select_from(Delivery).where(Delivery.status == "scheduled")
    )
    outstanding = session.scalar(
        select(func.coalesce(func.sum(Invoice.amount), 0)).where(
            Invoice.status == "unpaid"
        )
    )
    overdue = session.scalar(
        select(func.coalesce(func.sum(Invoice.amount), 0)).where(
            Invoice.status == "unpaid", Invoice.due_date < date.today()
        )
    )

    return {
        "summary": {
            "open_orders": open_orders or 0,
            "scheduled_deliveries": scheduled or 0,
            "outstanding_total": Decimal(outstanding or 0),
            "overdue_total": Decimal(overdue or 0),
        },
        "orders": _order_rows(session),
    }


@router.get("/orders", response_model=list[PortalOrderRow])
def list_orders(
    session: Session = Depends(get_portal_session),
    limit: int = Query(default=200, ge=1, le=200),
) -> list[dict]:
    return _order_rows(session, limit=limit)


@router.get("/sites", response_model=list[SiteOut])
def list_sites(session: Session = Depends(get_portal_session)) -> list[DeliverySite]:
    """The customer's own delivery sites, for the order form.

    No customer filter, again. The policy has already decided which sites
    these are.
    """
    return list(session.scalars(select(DeliverySite).order_by(DeliverySite.address)))


@router.get("/products", response_model=list[ProductOut])
def list_products(session: Session = Depends(get_portal_session)) -> list[Product]:
    """The catalogue. Shared across a distributor's customers, so no scoping
    beyond the tenant applies."""
    return list(session.scalars(select(Product).order_by(Product.name)))


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def place_order(
    payload: PortalOrderCreate,
    session: Session = Depends(get_portal_session),
    user: CurrentUser = Depends(get_current_user),
) -> Order:
    """Place an order against one of your own sites.

    ``customer_id`` is taken from the token, never from the body -- there is no
    field for it in the schema. Even if there were, the restrictive policy's
    check would reject a row written for anyone else, so the two defences
    disagree only in which error you get.

    The site lookup needs no ownership test. A site belonging to another
    customer of the same distributor reads as missing here, exactly as another
    tenant's does to staff.
    """
    site = session.get(DeliverySite, payload.site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown delivery site")

    product = session.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown product")

    if payload.requested_date < date.today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Requested date cannot be in the past",
        )

    order = Order(
        tenant_id=user.tenant_id,
        customer_id=user.customer_id,
        site_id=site.id,
        product_id=product.id,
        quantity_gal=payload.quantity_gal,
        # Snapshotted at the moment of ordering, same as a dispatcher-entered
        # order. The customer is quoted today's price and that is what the
        # invoice will say.
        unit_price=product.current_price,
        status="pending",
        requested_date=payload.requested_date,
    )
    session.add(order)
    session.flush()
    return order


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: uuid.UUID, session: Session = Depends(get_portal_session)
) -> Order:
    """Cancel an order of your own that has not been scheduled yet.

    Once a run is on the board a driver may already be routed around it, so
    cancelling becomes a conversation with the distributor rather than a
    button. Another customer's order id returns 404 for the usual reason: the
    lookup cannot see it.
    """
    order = session.get(Order, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if order.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A {order.status} order cannot be cancelled here — call your dispatcher",
        )
    order.status = "cancelled"
    session.flush()
    return order


@router.get("/invoices", response_model=list[PortalInvoiceRow])
def list_invoices(session: Session = Depends(get_portal_session)) -> list[dict]:
    """What you owe. Read-only: there is no endpoint here that settles one."""
    today = datetime.now(timezone.utc).date()
    rows = session.scalars(select(Invoice).order_by(Invoice.issued_at.desc()))

    return [
        {
            "id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "issued_at": invoice.issued_at,
            "due_date": invoice.due_date,
            "amount": invoice.amount,
            "status": invoice.status,
            "paid_at": invoice.paid_at,
            # Computed here rather than in the browser so every client agrees
            # on what "overdue" means, and on which day it is.
            "days_overdue": (
                (today - invoice.due_date).days
                if invoice.status == "unpaid" and invoice.due_date < today
                else 0
            ),
        }
        for invoice in rows
    ]
