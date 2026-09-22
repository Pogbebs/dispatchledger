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
