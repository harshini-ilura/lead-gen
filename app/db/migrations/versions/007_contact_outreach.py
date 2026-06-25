"""contacts outreach status

Revision ID: 007
Revises: 006
Create Date: 2026-06-19 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contacts", sa.Column("outreach_status", sa.Text(), nullable=True))
    op.create_index("ix_contacts_outreach_status", "contacts", ["outreach_status"])


def downgrade() -> None:
    op.drop_index("ix_contacts_outreach_status", "contacts")
    op.drop_column("contacts", "outreach_status")
