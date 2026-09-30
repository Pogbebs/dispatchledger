"""Invoices -- what was billed, what is owed, what is late.

Every completed delivery produces one, and until this router existed none of
them were visible anywhere in the application. The warehouse had receivables
ageing in fct_invoices and the operations team had no screen showing whether
a customer had paid.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from dispatchledger.deps import CurrentUser, get_session, require_role
from dispatchledger.models import Customer, Delivery, Invoice
from dispatchledger.schemas import InvoiceRow, InvoicesOut, InvoiceSummary

router = APIRouter(prefix="/invoices", tags=["invoices"])

ZERO = Decimal("0.00")


def _row(invoice: Invoice, customer_name: str, delivered_gal, today: date) -> dict:
    # Overdue is measured from the due date and only while unpaid. A paid
    # invoice settled three weeks late is not currently overdue, and showing
    # it as such would overstate receivables.
    overdue = 0
    if invoice.status == "unpaid" and invoice.due_date < today:
        overdue = (today - invoice.due_date).days

    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "customer_id": invoice.customer_id,
        "customer_name": customer_name,
        "issued_at": invoice.issued_at,
        "due_date": invoice.due_date,
        "amount": invoice.amount,
        "status": invoice.status,
        "paid_at": invoice.paid_at,
        "delivered_gal": delivered_gal,
        "days_overdue": overdue,
    }


@router.get("", response_model=InvoicesOut)
def list_invoices(
    session: Session = Depends(get_session),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> InvoicesOut:
    """Invoices for this tenant, newest first, with a receivables summary.

    No tenant filter in the query -- the row-security policy supplies it, the
    same as every other list endpoint here.
    """
    today = datetime.now(timezone.utc).date()

    stmt = (
        select(Invoice, Customer.name, Delivery.delivered_gal)
        .join(Customer, Customer.id == Invoice.customer_id)
        .outerjoin(Delivery, Delivery.id == Invoice.delivery_id)
        .order_by(Invoice.issued_at.desc(), Invoice.invoice_number.desc())
    )
    if status_filter:
        stmt = stmt.where(Invoice.status == status_filter)

    rows = [
        _row(invoice, customer_name, delivered_gal, today)
        for invoice, customer_name, delivered_gal in session.execute(
            stmt.limit(limit).offset(offset)
        )
    ]

    # The summary covers every invoice for the tenant, not just the page being
    # shown. "You are owed $312,000" is a fact about the business; making it
    # depend on the current filter would produce a headline that changes as
    # you click around.
    everything = session.execute(
        select(Invoice.status, Invoice.amount, Invoice.due_date)
    ).all()

    outstanding = [(a, d) for s, a, d in everything if s == "unpaid"]
    overdue = [(a, d) for a, d in outstanding if d < today]
    paid = [a for s, a, _ in everything if s == "paid"]

    summary = InvoiceSummary(
        outstanding_count=len(outstanding),
        outstanding_total=sum((a for a, _ in outstanding), ZERO),
        overdue_count=len(overdue),
        overdue_total=sum((a for a, _ in overdue), ZERO),
        paid_count=len(paid),
        paid_total=sum(paid, ZERO),
    )

    return InvoicesOut(rows=[InvoiceRow(**r) for r in rows], summary=summary)


@router.post("/{invoice_id}/pay", response_model=InvoiceRow)
def mark_paid(
    invoice_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_role("admin", "dispatcher")),
) -> InvoiceRow:
    """Record payment. Drivers cannot; they deliver fuel, not receivables."""
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        # Another tenant's invoice id lands here too, and must look absent.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    if invoice.status == "paid":
        raise HTTPException(status.HTTP_409_CONFLICT, "Invoice is already paid")
    if invoice.status == "void":
        raise HTTPException(status.HTTP_409_CONFLICT, "Invoice is void")

    invoice.status = "paid"
    invoice.paid_at = datetime.now(timezone.utc)
    session.flush()

    customer = session.get(Customer, invoice.customer_id)
    delivery = session.get(Delivery, invoice.delivery_id)
    return InvoiceRow(
        **_row(
            invoice,
            customer.name,
            delivery.delivered_gal if delivery else None,
            datetime.now(timezone.utc).date(),
        )
    )
