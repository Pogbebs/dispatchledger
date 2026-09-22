"""Seed the database with two tenants of realistic fake data.

Run as the owner role (dispatch), which is a superuser and therefore bypasses
row-level security. The application never connects this way.
"""

import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from faker import Faker
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from dispatchledger.db import engine
from dispatchledger.security import hash_password
from dispatchledger.models import (
    Customer,
    Delivery,
    DeliverySite,
    Invoice,
    Order,
    Product,
    Tenant,
    User,
)

fake = Faker("en_US")
Faker.seed(42)
random.seed(42)

TENANTS = [
    ("Gulf Coast Fuel Co.", "gulf-coast"),
    ("Lone Star Bulk Supply", "lone-star"),
]

PRODUCTS = [
    ("Diesel #2", Decimal("3.8420")),
    ("Unleaded 87", Decimal("3.1150")),
    ("DEF", Decimal("2.4500")),
]

# Every demo account shares one password. Hashed once, because bcrypt is
# deliberately slow and hashing it per user would make seeding crawl.
DEMO_PASSWORD = "demo1234"
DEMO_HASH = hash_password(DEMO_PASSWORD)


def wipe(session: Session) -> None:
    """Clear existing data, children first so foreign keys stay satisfied."""
    for model in (Invoice, Delivery, Order, DeliverySite, Product, User, Customer, Tenant):
        session.execute(delete(model))
    session.commit()


def seed_tenant(session: Session, name: str, slug: str) -> None:
    tenant = Tenant(name=name, slug=slug)
    session.add(tenant)
    session.flush()  # assigns tenant.id

    # --- people ---
    users = [
        User(
            tenant_id=tenant.id,
            email=f"admin@{slug}.example.com",
            full_name=fake.name(),
            role="admin",
            password_hash=DEMO_HASH,
        ),
        User(
            tenant_id=tenant.id,
            email=f"dispatch@{slug}.example.com",
            full_name=fake.name(),
            role="dispatcher",
            password_hash=DEMO_HASH,
        ),
    ]
    drivers = [
        User(
            tenant_id=tenant.id,
            email=f"driver{i}@{slug}.example.com",
            full_name=fake.name(),
            role="driver",
            password_hash=DEMO_HASH,
        )
        for i in range(1, 5)
    ]
    session.add_all(users + drivers)

    # --- catalog ---
    products = [
        Product(tenant_id=tenant.id, name=pname, unit="gal", current_price=price)
        for pname, price in PRODUCTS
    ]
    session.add_all(products)

    # --- customers and their tanks ---
    customers, sites = [], []
    for _ in range(12):
        customer = Customer(
            tenant_id=tenant.id,
            name=fake.company(),
            email=fake.company_email(),
            phone=fake.numerify("(###) ###-####"),
            payment_terms_days=random.choice([15, 30, 30, 45]),
        )
        customers.append(customer)
        session.add(customer)
        session.flush()

        for _ in range(random.randint(1, 3)):
            site = DeliverySite(
                tenant_id=tenant.id,
                customer_id=customer.id,
                address=f"{fake.street_address()}, {fake.city()}, TX {fake.postcode()}",
                tank_capacity_gal=Decimal(random.choice([2000, 5000, 10000, 12000])),
            )
            sites.append(site)
            session.add(site)

    session.flush()

    # --- six months of orders, deliveries and invoices ---
    invoice_seq = 1000
    today = date.today()

    for _ in range(220):
        site = random.choice(sites)
        product = random.choice(products)
        ordered = Decimal(random.randrange(500, 9000, 50))
        requested = today - timedelta(days=random.randint(0, 180))

        # Price drifts a little around the current list price.
        drift = Decimal(random.randint(-25, 25)) / Decimal(100)
        unit_price = max(Decimal("0.5000"), product.current_price + drift)

        order = Order(
            tenant_id=tenant.id,
            customer_id=site.customer_id,
            site_id=site.id,
            product_id=product.id,
            quantity_gal=ordered,
            unit_price=unit_price,
            status="pending",
            requested_date=requested,
        )
        session.add(order)
        session.flush()

        roll = random.random()
        if roll < 0.08:
            order.status = "cancelled"
            continue
        if roll < 0.18:
            order.status = "scheduled"
            session.add(
                Delivery(
                    tenant_id=tenant.id,
                    order_id=order.id,
                    driver_id=random.choice(drivers).id,
                    scheduled_at=datetime.combine(
                        requested, datetime.min.time(), tzinfo=timezone.utc
                    )
                    + timedelta(hours=random.randint(7, 17)),
                    status="scheduled",
                )
            )
            continue

        # Delivered. Trucks often leave slightly short of the ordered amount.
        scheduled_at = datetime.combine(
            requested, datetime.min.time(), tzinfo=timezone.utc
        ) + timedelta(hours=random.randint(7, 17))
        late_hours = random.choice([0, 0, 0, 1, 2, 26])
        delivered_at = scheduled_at + timedelta(hours=late_hours, minutes=random.randint(0, 59))
        delivered = (ordered * Decimal(random.randint(92, 100)) / Decimal(100)).quantize(
            Decimal("0.01")
        )

        order.status = "delivered"
        delivery = Delivery(
            tenant_id=tenant.id,
            order_id=order.id,
            driver_id=random.choice(drivers).id,
            scheduled_at=scheduled_at,
            delivered_at=delivered_at,
            delivered_gal=delivered,
            status="completed",
        )
        session.add(delivery)
        session.flush()

        customer = session.get(Customer, site.customer_id)
        issued = delivered_at.date()
        due = issued + timedelta(days=customer.payment_terms_days)
        amount = (delivered * unit_price).quantize(Decimal("0.01"))

        paid_at = None
        status = "unpaid"
        if due < today and random.random() < 0.85:
            status = "paid"
            paid_at = datetime.combine(
                due - timedelta(days=random.randint(-6, 10)),
                datetime.min.time(),
                tzinfo=timezone.utc,
            )
        elif due >= today and random.random() < 0.35:
            status = "paid"
            paid_at = datetime.combine(
                issued + timedelta(days=random.randint(1, 10)),
                datetime.min.time(),
                tzinfo=timezone.utc,
            )

        invoice_seq += 1
        session.add(
            Invoice(
                tenant_id=tenant.id,
                customer_id=customer.id,
                delivery_id=delivery.id,
                invoice_number=f"INV-{invoice_seq}",
                issued_at=issued,
                due_date=due,
                amount=amount,
                status=status,
                paid_at=paid_at,
            )
        )

    session.commit()
    print(f"  seeded {name}")


def main() -> None:
    with Session(engine) as session:
        wipe(session)
        for name, slug in TENANTS:
            seed_tenant(session, name, slug)

        counts = {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (Tenant, User, Customer, DeliverySite, Product, Order, Delivery, Invoice)
        }

    print("\nRow counts:")
    for table, count in counts.items():
        print(f"  {table:<16} {count}")


if __name__ == "__main__":
    main()
