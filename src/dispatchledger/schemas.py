"""Request and response shapes. Pydantic validates every payload at the edge."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

ORM = ConfigDict(from_attributes=True)


# ---------- auth ----------

class LoginRequest(BaseModel):
    tenant_slug: str = Field(min_length=1, max_length=100)
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ORM
    id: uuid.UUID
    email: str
    full_name: str
    role: str


class MeOut(UserOut):
    """Adds the tenant, so the UI can always show which company is in view."""

    tenant_id: uuid.UUID
    tenant_name: str
    tenant_slug: str
    # Present only for a customer login. The web app branches on this to
    # decide which application it is showing.
    customer_id: uuid.UUID | None = None
    customer_name: str | None = None


# ---------- customers ----------

class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    payment_terms_days: int = Field(default=30, ge=0, le=365)


class CustomerOut(BaseModel):
    model_config = ORM
    id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    payment_terms_days: int


# ---------- orders ----------

class OrderCreate(BaseModel):
    customer_id: uuid.UUID
    site_id: uuid.UUID
    product_id: uuid.UUID
    quantity_gal: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    requested_date: date


class OrderOut(BaseModel):
    model_config = ORM
    id: uuid.UUID
    customer_id: uuid.UUID
    site_id: uuid.UUID
    product_id: uuid.UUID
    quantity_gal: Decimal
    unit_price: Decimal
    status: str
    requested_date: date


# ---------- deliveries ----------

class DeliveryCreate(BaseModel):
    order_id: uuid.UUID
    driver_id: uuid.UUID | None = None
    scheduled_at: datetime


class DeliveryComplete(BaseModel):
    delivered_gal: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    delivered_at: datetime | None = None


class DeliveryOut(BaseModel):
    model_config = ORM
    id: uuid.UUID
    order_id: uuid.UUID
    driver_id: uuid.UUID | None
    scheduled_at: datetime
    delivered_at: datetime | None
    delivered_gal: Decimal | None
    status: str


# ---------- catalog ----------

class ProductOut(BaseModel):
    model_config = ORM
    id: uuid.UUID
    name: str
    unit: str
    current_price: Decimal


class SiteOut(BaseModel):
    model_config = ORM
    id: uuid.UUID
    customer_id: uuid.UUID
    address: str
    tank_capacity_gal: Decimal


# ---------- board rows ----------
# List endpoints return names alongside ids so the UI does not have to fetch
# every customer and product to render one table.

class OrderRow(OrderOut):
    customer_name: str
    product_name: str
    site_address: str


class DeliveryRow(DeliveryOut):
    customer_name: str
    product_name: str
    ordered_gal: Decimal
    driver_name: str | None = None


# ---------- insights ----------
# These come from the warehouse rather than the application tables, so there
# is no ORM model behind them: the rows are read as plain SQL and validated
# here on the way out.

class WeeklyPricePosition(BaseModel):
    week_start: date
    delivery_count: int
    delivered_gal: Decimal
    revenue: Decimal
    avg_price: Decimal
    market_price: Decimal
    price_delta: Decimal
    margin_vs_benchmark: Decimal


class InsightsSummary(BaseModel):
    weeks_covered: int
    delivery_count: int
    delivered_gal: Decimal
    revenue: Decimal
    avg_price: Decimal
    market_price: Decimal
    price_delta: Decimal
    margin_vs_benchmark: Decimal
    first_week: date
    latest_week: date


class InsightsOut(BaseModel):
    """``warehouse_available`` is false before the first dbt build.

    The API and the warehouse are built by different tools on different
    schedules, so a freshly migrated database has application tables and no
    marts. Saying so plainly lets the UI explain the gap instead of showing
    an error it cannot account for.
    """

    warehouse_available: bool
    weeks: list[WeeklyPricePosition]
    summary: InsightsSummary | None


# ---------- scheduling ----------

class DeliveryReschedule(BaseModel):
    """Both fields optional: a reassignment and a date change are separate acts.

    ``driver_id`` set to null is meaningful -- it unassigns -- so the model
    has to distinguish "not supplied" from "supplied as null". That is what
    ``model_fields_set`` is for in the handler.
    """

    driver_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None


class DriverOut(BaseModel):
    """Only what a scheduling dropdown needs. No email, no role, no hash."""

    model_config = ORM
    id: uuid.UUID
    full_name: str


class SiteCreate(BaseModel):
    customer_id: uuid.UUID
    address: str = Field(min_length=1, max_length=300)
    tank_capacity_gal: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


# ---------- invoices ----------

class InvoiceRow(BaseModel):
    model_config = ORM
    id: uuid.UUID
    invoice_number: str
    customer_id: uuid.UUID
    customer_name: str
    issued_at: date
    due_date: date
    amount: Decimal
    status: str
    paid_at: datetime | None
    delivered_gal: Decimal | None
    # Days past due, computed server-side. The client's clock is not the
    # authority on whether a bill is late.
    days_overdue: int


class InvoiceSummary(BaseModel):
    outstanding_count: int
    outstanding_total: Decimal
    overdue_count: int
    overdue_total: Decimal
    paid_count: int
    paid_total: Decimal


class InvoicesOut(BaseModel):
    rows: list[InvoiceRow]
    summary: InvoiceSummary


# ---------- the customer portal ----------

class InviteCreate(BaseModel):
    """What a dispatcher supplies to invite a customer contact."""

    customer_id: uuid.UUID
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InviteOut(BaseModel):
    """The response carries the token exactly once.

    Only its hash is stored, so this is the only moment the plaintext exists
    anywhere. The dispatcher copies the link from here; nothing can show it
    again, which is the property that makes the stored row harmless.
    """

    id: uuid.UUID
    customer_id: uuid.UUID
    email: EmailStr
    full_name: str
    expires_at: datetime
    accept_path: str


class InviteRow(BaseModel):
    """An invitation as the staff list shows it. No token, ever."""

    model_config = ORM
    id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str
    email: EmailStr
    full_name: str
    expires_at: datetime
    accepted_at: datetime | None
    status: str


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class PortalOrderCreate(BaseModel):
    """A customer placing their own order.

    No customer_id: it comes from the token. There is deliberately no field
    here for a client to set, which is the same reason no endpoint takes a
    tenant id.
    """

    site_id: uuid.UUID
    product_id: uuid.UUID
    quantity_gal: Decimal = Field(gt=0, le=Decimal("100000"))
    requested_date: date


class PortalOrderRow(BaseModel):
    """What the customer sees of their own order.

    unit_price is included because it is the price they agreed to pay. What is
    absent is anything about the distributor's position on that price -- cost,
    margin, benchmark. Those live in the Insights mart, which this role has no
    grant on at all.
    """

    model_config = ORM
    id: uuid.UUID
    site_address: str
    product_name: str
    quantity_gal: Decimal
    unit_price: Decimal
    status: str
    requested_date: date
    scheduled_at: datetime | None
    delivered_at: datetime | None
    delivered_gal: Decimal | None


class PortalInvoiceRow(BaseModel):
    model_config = ORM
    id: uuid.UUID
    invoice_number: str
    issued_at: date
    due_date: date
    amount: Decimal
    status: str
    paid_at: datetime | None
    days_overdue: int


class PortalSummary(BaseModel):
    open_orders: int
    scheduled_deliveries: int
    outstanding_total: Decimal
    overdue_total: Decimal


class PortalOverview(BaseModel):
    summary: PortalSummary
    orders: list[PortalOrderRow]
