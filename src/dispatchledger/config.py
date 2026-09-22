"""Settings, read from the environment with local-development defaults."""

import os

# The application connects as dispatch_app: a plain login role that owns
# nothing and is not a superuser, so row-level security actually applies to it.
APP_DATABASE_URL = os.getenv(
    "APP_DATABASE_URL",
    "postgresql+psycopg://dispatch_app:dispatch_app@localhost:5433/dispatchledger",
)

# The owner role. Used ONLY by the login endpoint, which has to find a tenant
# and a user before any tenant is known, and by migrations and seeding.
ADMIN_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://dispatch:dispatch@localhost:5433/dispatchledger",
)

# Never commit a real secret. In deployment this comes from the environment.
JWT_SECRET = os.getenv(
    "JWT_SECRET", "dev-only-secret-replace-in-deployment-32b"
)
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "60"))
