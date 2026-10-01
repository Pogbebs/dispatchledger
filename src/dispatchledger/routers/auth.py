"""Login. The one place that reads across tenants, and only to resolve one."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from dispatchledger.db import admin_session
from dispatchledger.deps import CurrentUser, get_current_user, get_identity_session
from dispatchledger.models import Customer, CustomerInvite, Tenant, User
from dispatchledger.schemas import (
    AcceptInviteRequest,
    LoginRequest,
    MeOut,
    TokenResponse,
)
from dispatchledger.security import (
    create_access_token,
    hash_invite_token,
    hash_password,
    verify_password,
)

router = APIRouter(tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    """Authenticate against one tenant, named by slug.

    This runs on the admin connection because there is no tenant set yet, and
    under row-level security an unscoped lookup would return nothing. It is
    the only endpoint that does so, and it reads exactly two rows: the tenant
    with that slug, and the user with that email inside it.
    """
    with admin_session() as session:
        tenant = session.scalar(select(Tenant).where(Tenant.slug == payload.tenant_slug))
        user = None
        if tenant is not None:
            user = session.scalar(
                select(User).where(
                    User.tenant_id == tenant.id,
                    User.email == payload.email,
                )
            )

        # One message for every failure, so the response cannot be used to
        # discover which tenants or accounts exist.
        if user is None or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

        return TokenResponse(
            access_token=create_access_token(
                user_id=user.id,
                tenant_id=user.tenant_id,
                role=user.role,
                customer_id=user.customer_id,
            )
        )


@router.get("/me", response_model=MeOut)
def me(
    current: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_identity_session),
) -> dict:
    """Runs on whichever scoped session the caller's role allows.

    For a customer that is the portal connection, so even this lookup is
    filtered to their own row. The restrictive policy on ``users`` means a
    customer reading themselves back cannot enumerate the distributor's staff
    by changing an id.
    """
    user = session.get(User, current.id)
    tenant = session.get(Tenant, current.tenant_id)
    if user is None or tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    # The company name a customer sees is their own, not the distributor's
    # customer list -- it comes back through the same filtered session.
    customer_name = None
    if user.customer_id is not None:
        customer = session.get(Customer, user.customer_id)
        customer_name = customer.name if customer else None

    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "tenant_slug": tenant.slug,
        "customer_id": user.customer_id,
        "customer_name": customer_name,
    }


@router.post(
    "/invites/accept", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
def accept_invite(payload: AcceptInviteRequest) -> TokenResponse:
    """Turn an invitation into a login, and sign the customer straight in.

    Runs on the admin connection for the same reason login does: the caller
    has no account yet, so there is no tenant to scope a session to. It reads
    and writes exactly the rows the token identifies.

    The token is looked up by hash. The plaintext exists only in the link the
    distributor sent, never in the database, so a copy of this table is not a
    set of working invitations.
    """
    token_hash = hash_invite_token(payload.token)

    with admin_session() as session:
        invite = session.scalar(
            select(CustomerInvite).where(CustomerInvite.token_hash == token_hash)
        )

        # One message for every failure: unknown, already used, expired. A
        # response that distinguished them would let someone probe for live
        # invitations.
        now = datetime.now(timezone.utc)
        if (
            invite is None
            or invite.accepted_at is not None
            or invite.expires_at <= now
        ):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "This invitation is not valid"
            )

        existing = session.scalar(
            select(User).where(
                User.tenant_id == invite.tenant_id, User.email == invite.email
            )
        )
        if existing is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "An account with this email already exists"
            )

        user = User(
            tenant_id=invite.tenant_id,
            email=invite.email,
            full_name=invite.full_name,
            role="customer",
            customer_id=invite.customer_id,
            password_hash=hash_password(payload.password),
        )
        session.add(user)
        invite.accepted_at = now
        session.commit()
        session.refresh(user)

        return TokenResponse(
            access_token=create_access_token(
                user_id=user.id,
                tenant_id=user.tenant_id,
                role=user.role,
                customer_id=user.customer_id,
            )
        )
