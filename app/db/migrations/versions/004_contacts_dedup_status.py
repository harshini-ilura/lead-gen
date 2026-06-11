"""contacts dedup keys + company contact_status

Revision ID: 004
Revises: 003
Create Date: 2026-06-11 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # contacts: dedup anchor (company_id, normalized_name)
    op.add_column("contacts", sa.Column("normalized_name", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_contacts_company_norm", "contacts", ["company_id", "normalized_name"]
    )
    # contact_emails: one row per (contact, email)
    op.create_unique_constraint(
        "uq_contact_emails_contact_email", "contact_emails", ["contact_id", "email"]
    )
    # companies: Phase 3 state machine
    op.add_column(
        "companies",
        sa.Column("contact_status", sa.Text(), server_default="crawled", nullable=True),
    )


def downgrade() -> None:
    op.drop_column("companies", "contact_status")
    op.drop_constraint("uq_contact_emails_contact_email", "contact_emails", type_="unique")
    op.drop_constraint("uq_contacts_company_norm", "contacts", type_="unique")
    op.drop_column("contacts", "normalized_name")
