"""contacts handoff status

Revision ID: 006
Revises: 005
Create Date: 2026-06-18 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("handoff_status", sa.Text(), server_default="pending", nullable=True),
    )
    op.add_column(
        "contacts", sa.Column("handed_off_at", sa.TIMESTAMP(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("contacts", "handed_off_at")
    op.drop_column("contacts", "handoff_status")
