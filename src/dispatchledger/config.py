"""Settings, read from the environment.

A ``.env`` file in the repository root is loaded first when one exists, so a
fresh clone needs no shell setup: copy ``.env.example`` to ``.env`` and run.
It is gitignored, and real environment variables always win over it.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_env_file(path: Path) -> None:
    """Read ``KEY=value`` lines into the environment if they are not set.

    Deliberately not python-dotenv. The requirement is a dozen lines, and a
    dependency that imports in every process -- the API, the migrations, the
    seed script, every test run -- should earn its place.

    ``setdefault`` rather than assignment matters: a platform's own
    configuration must never be overridden by a file that happened to be
    deployed alongside the code.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(REPO_ROOT / ".env")


def _required(name: str, why: str) -> str:
    """A setting with no fallback, because the fallback would be the bug.

    A default that works is more dangerous than one that does not: nothing
    tells you it is wrong. This is the same reasoning as the row-security
    policies themselves -- when the tenant is unset the database returns zero
    rows rather than every row. Fail closed.
    """
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. {why}\n"
            f"For local development: copy .env.example to .env in the "
            f"repository root. In deployment: set it in the platform's "
            f"environment configuration."
        )
    return value


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

# No default, ever. This key signs the token that carries the tenant id, so
# anyone holding it can mint a token for any tenant and read that company's
# data. A shared default published in a public repository would hand that to
# the internet -- and would do it silently, on a deployment that looked fine.
JWT_SECRET = _required(
    "JWT_SECRET",
    "It signs the tokens that carry tenant identity; a known value lets "
    "anyone forge access to any tenant.",
)

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "60"))
