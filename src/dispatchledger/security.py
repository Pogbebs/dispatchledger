"""Password hashing, access tokens, and invitation tokens."""

import hashlib
import secrets
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


def create_access_token(
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role: str,
    customer_id: uuid.UUID | None = None,
) -> str:
    """The tenant travels in the token, so every later request is self-scoping.

    For a customer login the customer travels with it, for the same reason and
    with the same consequence: there is no request parameter naming whose
    orders to return, so there is nothing for a client to tamper with.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tenant": str(tenant_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES),
    }
    if customer_id is not None:
        payload["customer"] = str(customer_id)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError on anything wrong: expiry, signature, structure."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def new_invite_token() -> str:
    """A single-use invitation token.

    url-safe so it survives being pasted into a link, and 32 bytes of entropy
    because the only thing standing between this string and a customer account
    is that nobody can guess it.
    """
    return secrets.token_urlsafe(32)


def hash_invite_token(token: str) -> str:
    """What gets stored. SHA-256, not bcrypt, and the difference matters.

    bcrypt is deliberately slow to make guessing a human-chosen password
    expensive. An invite token is 256 bits of randomness that nobody guesses,
    so the cost buys nothing -- and this runs on every lookup, where a slow
    hash would turn the accept endpoint into a way to tie up workers.

    Stored hashed all the same: until it is used, the token in the link is a
    credential, and a dump of this table should not be a set of live ones.
    """
    return hashlib.sha256(token.encode()).hexdigest()
