"""Inviting a customer to the portal. Staff side.

A customer cannot sign themselves up, and that is a design decision rather
than a missing feature. Open signup would let anyone insert themselves into a
distributor's customer book, which is precisely the boundary this project
exists to defend. The relationship is created by the distributor, so the
account is provisioned by the distributor too.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from dispatchledger.deps import CurrentUser, get_session, require_role
from dispatchledger.models import Customer, CustomerInvite, User
from dispatchledger.schemas import InviteCreate, InviteOut, InviteRow
from dispatchledger.security import hash_invite_token, new_invite_token

router = APIRouter(prefix="/invites", tags=["invites"])


@router.get("", response_model=list[InviteRow])
def list_invites(session: Session = Depends(get_session)) -> list[dict]:
    """Outstanding and recent invitations, with no token in sight.

    The token is unrecoverable by design: only its hash was ever stored. If an
    invitation is lost, the answer is to issue another one, not to look the
    old one up.
    """
    now = datetime.now(timezone.utc)
    rows = session.execute(
        select(CustomerInvite, Customer.name)
        .join(Customer, Customer.id == CustomerInvite.customer_id)
        .order_by(CustomerInvite.created_at.desc())
    )

    return [
        {
            "id": invite.id,
            "customer_id": invite.customer_id,
            "customer_name": customer_name,
            "email": invite.email,
            "full_name": invite.full_name,
            "expires_at": invite.expires_at,
            "accepted_at": invite.accepted_at,
            "status": (
                "accepted"
                if invite.accepted_at is not None
                else "expired"
                if invite.expires_at <= now
                else "pending"
            ),
        }
        for invite, customer_name in rows
    ]


@router.post("", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
def create_invite(
    payload: InviteCreate,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_role("admin", "dispatcher")),
) -> dict:
    """Issue a single-use invitation and return its link exactly once.

    The plaintext token is in this response and nowhere else. Storing only the
    hash means a copy of the table is not a set of working invitations, and it
    means this endpoint is the only moment the link can be captured — which is
    why the UI shows it with a copy button rather than burying it in a toast.
    """
    customer = session.get(Customer, payload.customer_id)
    if customer is None:
        # Another tenant's customer id reads as missing: the lookup runs under
        # the policy. Nothing here compares tenants.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")

    existing_user = session.scalar(select(User).where(User.email == payload.email))
    if existing_user is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{payload.email} already has an account with you",
        )

    live = session.scalar(
        select(CustomerInvite).where(
            CustomerInvite.email == payload.email,
            CustomerInvite.accepted_at.is_(None),
            CustomerInvite.expires_at > datetime.now(timezone.utc),
        )
    )
    if live is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An invitation for this address is still open. Let it expire or "
            "ask them to use it.",
        )

    token = new_invite_token()
    invite = CustomerInvite(
        tenant_id=user.tenant_id,
        customer_id=customer.id,
        email=payload.email,
        full_name=payload.full_name,
        token_hash=hash_invite_token(token),
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=payload.expires_in_days),
    )
    session.add(invite)
    session.flush()

    return {
        "id": invite.id,
        "customer_id": invite.customer_id,
        "email": invite.email,
        "full_name": invite.full_name,
        "expires_at": invite.expires_at,
        # A path rather than a full URL: the API does not know the host it is
        # being served under, and guessing one is how a link ends up pointing
        # at localhost in a production email.
        "accept_path": f"/invite/{token}",
    }


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(
    invite_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_role("admin", "dispatcher")),
) -> None:
    """Withdraw an invitation that has not been used.

    Deleting the row is what makes the outstanding link stop working: the
    accept endpoint finds nothing to match the hash against. An already
    accepted invitation is kept, because it is now the record of how an
    account came to exist.
    """
    invite = session.get(CustomerInvite, invite_id)
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    if invite.accepted_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This invitation was already accepted; disable the account instead",
        )
    session.delete(invite)
    session.flush()
