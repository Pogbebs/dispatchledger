"""Let staff revoke an invitation

Revision ID: d4b9e71a2c38
Revises: c7e2b41f5a93
Create Date: 2026-10-01

The portal migration granted dispatch_app SELECT, INSERT and UPDATE on
customer_invites, which covers listing and accepting. Revoking deletes the
row -- that is what makes the outstanding link stop working -- and DELETE was
not in the list.

The endpoint, its role check and its 409 on an already-accepted invitation
were all written and all correct. The failure would have been a permission
error from the database on the first click, which is the right place for it to
fail but the wrong reason.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d4b9e71a2c38"
down_revision: Union[str, Sequence[str], None] = "c7e2b41f5a93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("GRANT DELETE ON customer_invites TO dispatch_app")


def downgrade() -> None:
    op.execute("REVOKE DELETE ON customer_invites FROM dispatch_app")
