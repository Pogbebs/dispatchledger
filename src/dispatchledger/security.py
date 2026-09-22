"""Password hashing and access tokens."""

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from dispatchledger.config import ACCESS_TOKEN_MINUTES, JWT_ALGORITHM, JWT_SECRET


def hash_password(plain: str) -> str:
    """bcrypt with a per-password salt. Never store or log the plaintext."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        # A malformed hash in the database should read as "wrong password",
        # not crash the login endpoint.
        return False


def create_access_token(*, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> str:
    """The tenant travels in the token, so every later request is self-scoping."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tenant": str(tenant_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError on anything wrong: expiry, signature, structure."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
