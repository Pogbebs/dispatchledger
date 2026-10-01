"""Request dependencies: who is calling, and a session scoped to their tenant."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from dispatchledger.db import customer_session, tenant_session
from dispatchledger.security import decode_access_token

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    # Set only for a customer login. For staff it is None, and the portal
    # dependency refuses to build a session without it.
    customer_id: uuid.UUID | None = None


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(credentials.credentials)
        customer = payload.get("customer")
        return CurrentUser(
            id=uuid.UUID(payload["sub"]),
            tenant_id=uuid.UUID(payload["tenant"]),
            role=payload["role"],
            customer_id=uuid.UUID(customer) if customer else None,
        )
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def get_session(user: CurrentUser = Depends(get_current_user)) -> Iterator[Session]:
    """The tenant comes from the signed token, never from the request body.

    A client cannot ask for another tenant's data: there is no parameter to
    tamper with. Everything the handler does inside this session runs under
    the row-security policy for exactly this tenant.

    Customers are refused here rather than endpoint by endpoint. This session
    connects as ``dispatch_app``, which sees the whole tenant -- correct for
    staff, catastrophic for a customer. Several staff endpoints are read-only
    and so carry no ``require_role`` guard of their own; without this check, a
    customer token would sail through them and list every order the
    distributor has. One refusal in the shared dependency is harder to forget
    than a guard repeated on every route.
    """
    if user.role == "customer":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Customer accounts use the portal endpoints"
        )
    with tenant_session(user.tenant_id) as session:
        yield session


def get_identity_session(
    user: CurrentUser = Depends(get_current_user),
) -> Iterator[Session]:
    """Whichever session matches the caller, for endpoints both sides use.

    Only ``/me`` needs this: everyone has to be able to ask who they are, and
    the answer has to come back through the connection their role is allowed
    to use.
    """
    if user.role == "customer" and user.customer_id is not None:
        with customer_session(user.tenant_id, user.customer_id) as session:
            yield session
    else:
        with tenant_session(user.tenant_id) as session:
            yield session


def get_portal_session(
    user: CurrentUser = Depends(get_current_user),
) -> Iterator[Session]:
    """A session for the customer portal, on the restricted role.

    Two guards before any query runs, both of which should be impossible:

    * the caller must hold a customer token, so a staff token cannot reach a
      portal endpoint even if the route is guessed;
    * that token must carry a customer id, because a session without one would
      connect as ``dispatch_portal`` with ``app.current_customer`` unset.

    The second case is harmless by design -- the policy would match no rows --
    but an empty screen is a bad way to learn that a token was malformed, so it
    is refused with a reason instead.
    """
    if user.role != "customer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a customer account")
    if user.customer_id is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Token carries no customer identity"
        )

    with customer_session(user.tenant_id, user.customer_id) as session:
        yield session


def require_role(*allowed: str):
    """Coarse role check at the edge. RLS is what protects the data."""

    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires one of: {', '.join(allowed)}",
            )
        return user

    return dependency
