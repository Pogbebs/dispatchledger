"""Login. The one place that reads across tenants, and only to resolve one."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from dispatchledger.db import admin_session
from dispatchledger.deps import CurrentUser, get_current_user, get_session
from dispatchledger.models import Tenant, User
from dispatchledger.schemas import LoginRequest, MeOut, TokenResponse
from dispatchledger.security import create_access_token, verify_password

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
                user_id=user.id, tenant_id=user.tenant_id, role=user.role
            )
        )


@router.get("/me", response_model=MeOut)
def me(
    current: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Runs on the tenant-scoped session, so the tenant lookup is policy-checked."""
    user = session.get(User, current.id)
    tenant = session.get(Tenant, current.tenant_id)
    if user is None or tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "tenant_slug": tenant.slug,
    }
