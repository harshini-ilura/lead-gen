"""contact_emails.is_primary

Revision ID: 005
Revises: 004
Create Date: 2026-06-13 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contact_emails",
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=True),
    )
    op.create_index(
        "ix_contact_emails_contact_primary", "contact_emails", ["contact_id", "is_primary"]
    )


def downgrade() -> None:
    op.drop_index("ix_contact_emails_contact_primary", "contact_emails")
    op.drop_column("contact_emails", "is_primary")
