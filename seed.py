"""Seed the database with two tenants of realistic fake data.

Run as the owner role (dispatch), which is a superuser and therefore bypasses
row-level security. The application never connects this way.
"""

import random
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from faker import Faker
from sqlalchemy import delete, func, select, text
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

SERIES_ID = "EMD_EPD2D_PTE_NUS_DPG"

# Fallback prices, used only when no benchmark has been loaded. They are
# necessarily a guess at "roughly now", and a guess goes stale -- an earlier
# version of this file priced diesel at $3.84, which was reasonable when it was
# written and badly wrong a year later against a market that had nearly
# doubled. Nothing warned about it, because every number in the warehouse was
# internally consistent; only comparing against the outside world showed it.
#
# Hence the design below: when real prices are available, the seed uses them
# and this constant never applies.
FALLBACK_DIESEL = Decimal("3.8420")

# Gasoline tracks diesel loosely and trades a little under it. DEF is a urea
# solution rather than a fuel and does not move with the crude complex at all,
# so it is held flat.
GASOLINE_RATIO = Decimal("0.86")
DEF_PRICE = Decimal("2.4500")

# What each distributor adds over the national retail benchmark. Distributors
# do not sell at the benchmark -- the spread is the business, and it is the
# number the Insights page exists to show. The two tenants are given different
# spreads so the demo has something to compare.
TENANT_MARGIN = {
    "gulf-coast": (Decimal("0.22"), Decimal("0.34")),
    "lone-star": (Decimal("0.30"), Decimal("0.44")),
}

PRODUCT_NAMES = ["Diesel #2", "Unleaded 87", "DEF"]


def load_benchmark(session: Session) -> tuple[list[date], list[Decimal]]:
    """The EIA price series, if the pipeline has ever run.

    Seeding from real market data rather than a hard-coded constant is what
    keeps the demo honest: the fictional trading then sits at a believable
    spread over whatever the market was actually doing that week, instead of
    drifting further from reality every month the repository ages.

    Returns empty lists when nothing has been loaded, which the callers treat
    as "fall back to fixed prices".
    """
    rows = session.execute(
        text(
            "SELECT price_date, price_usd_per_gal FROM raw_fuel_prices "
            "WHERE series_id = :series ORDER BY price_date"
        ),
        {"series": SERIES_ID},
    ).all()
    return [row[0] for row in rows], [Decimal(row[1]) for row in rows]


def market_on(curve: tuple[list[date], list[Decimal]], when: date) -> Decimal | None:
    """The most recent week published on or before ``when``.

    The same as-of rule the warehouse uses in fct_price_benchmark. Matching it
    here is deliberate: if the seed priced an order against a week that had not
    been published yet, the benchmark model would compare it to a different
    week and the demo would show a spread nobody chose.
    """
    dates, prices = curve
    if not dates:
        return None
    index = bisect_right(dates, when)
    # Orders predating the series take its first week rather than nothing.
    return prices[index - 1] if index else prices[0]


def price_for(
    product_name: str,
    when: date,
    curve: tuple[list[date], list[Decimal]],
    margin: tuple[Decimal, Decimal],
) -> Decimal:
    """What this tenant charged for this product on this date."""
    if product_name == "DEF":
        return DEF_PRICE

    base = market_on(curve, when) or FALLBACK_DIESEL
    if product_name != "Diesel #2":
        base *= GASOLINE_RATIO

    low, high = margin
    spread = low + (high - low) * Decimal(random.random())
    return (base + spread).quantize(Decimal("0.0001"))

# Every demo account shares one password. Hashed once, because bcrypt is
# deliberately slow and hashing it per user would make seeding crawl.
DEMO_PASSWORD = "demo1234"
DEMO_HASH = hash_password(DEMO_PASSWORD)


def wipe(session: Session) -> None:
    """Clear existing data, children first so foreign keys stay satisfied."""
    for model in (Invoice, Delivery, Order, DeliverySite, Product, User, Customer, Tenant):
        session.execute(delete(model))
    session.commit()


def seed_tenant(
    session: Session,
    name: str,
    slug: str,
    curve: tuple[list[date], list[Decimal]],
) -> None:
    margin = TENANT_MARGIN[slug]
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
    # The list price is today's, which is what a customer would be quoted now.
    # Each order snapshots its own price at order time, so past invoices are
    # unaffected by this moving -- the reason unit_price exists on orders at
    # all rather than being read from here.
    products = [
        Product(
            tenant_id=tenant.id,
            name=pname,
            unit="gal",
            current_price=price_for(pname, date.today(), curve, margin),
        )
        for pname in PRODUCT_NAMES
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

        # Priced against the market as it stood on the requested date, not
        # against today's list price. Fuel moved by more than a dollar a gallon
        # over the seeded period, so pricing six months of history at one
        # figure is the difference between a demo that looks like a business
        # and one that looks like it sold below cost all year.
        unit_price = price_for(product.name, requested, curve, margin)

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
        curve = load_benchmark(session)
        if curve[0]:
            print(
                f"Pricing against {len(curve[0])} weeks of EIA data "
                f"({curve[0][0]} to {curve[0][-1]}, "
                f"${curve[1][0]} to ${curve[1][-1]})."
            )
        else:
            print(
                "No EIA prices loaded: falling back to fixed list prices.\n"
                "Run the Airflow DAG (or the fetch task) before seeding to get "
                "demo data priced against the real market."
            )

        wipe(session)
        for name, slug in TENANTS:
            seed_tenant(session, name, slug, curve)

        counts = {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (Tenant, User, Customer, DeliverySite, Product, Order, Delivery, Invoice)
        }

    print("\nRow counts:")
    for table, count in counts.items():
        print(f"  {table:<16} {count}")


if __name__ == "__main__":
    main()
