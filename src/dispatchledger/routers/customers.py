"""Customers. Note the absence of any tenant filter in these queries."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from dispatchledger.deps import CurrentUser, get_current_user, get_session, require_role
from dispatchledger.models import Customer
from dispatchledger.schemas import CustomerCreate, CustomerOut

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=list[CustomerOut])
def list_customers(
    session: Session = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Customer]:
    # No WHERE tenant_id here, and none is needed: the row-security policy
    # adds it. This is the whole point of the design.
    stmt = select(Customer).order_by(Customer.name).limit(limit).offset(offset)
    return list(session.scalars(stmt))


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> Customer:
    customer = session.get(Customer, customer_id)
    if customer is None:
        # Another tenant's id lands here too. The policy hid the row, so the
        # handler genuinely cannot tell the difference -- and 404 rather than
        # 403 means the response does not confirm the id exists elsewhere.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return customer


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreate,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_role("admin", "dispatcher")),
) -> Customer:
    customer = Customer(tenant_id=user.tenant_id, **payload.model_dump())
    session.add(customer)
    session.flush()
    return customer
