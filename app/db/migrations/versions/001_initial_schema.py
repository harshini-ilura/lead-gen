"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-01 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "companies",
        sa.Column("company_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("place_id", sa.Text(), nullable=True),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=True),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("subcategory", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("emirate", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), server_default="AE", nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("phone_e164", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("linkedin_url", sa.Text(), nullable=True),
        sa.Column("instagram_url", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Double(), nullable=True),
        sa.Column("longitude", sa.Double(), nullable=True),
        sa.Column("google_rating", sa.Numeric(2, 1), nullable=True),
        sa.Column("rating_count", sa.Integer(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("confidence_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("crawl_status", sa.Text(), server_default="discovered", nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("company_id"),
        sa.UniqueConstraint("place_id"),
    )
    op.create_index("idx_companies_domain", "companies", ["domain"])
    op.create_index("idx_companies_phone", "companies", ["phone_e164"])
    op.create_index(
        "idx_companies_norm_name",
        "companies",
        ["normalized_name"],
        postgresql_using="gin",
        postgresql_ops={"normalized_name": "gin_trgm_ops"},
    )

    op.create_table(
        "contacts",
        sa.Column("contact_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=True),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("job_title", sa.Text(), nullable=True),
        sa.Column("seniority", sa.Text(), nullable=True),
        sa.Column("linkedin_url", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Numeric(3, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.company_id"]),
        sa.PrimaryKeyConstraint("contact_id"),
    )

    op.create_table(
        "contact_emails",
        sa.Column("email_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("contact_id", sa.BigInteger(), nullable=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=True),
        sa.Column("generation_confidence", sa.Text(), nullable=True),
        sa.Column(
            "verification_status", sa.Text(), server_default="unknown", nullable=True
        ),
        sa.Column("verification_source", sa.Text(), nullable=True),
        sa.Column(
            "is_role_email", sa.Boolean(), server_default="false", nullable=True
        ),
        sa.Column("verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.contact_id"]),
        sa.PrimaryKeyConstraint("email_id"),
    )

    op.create_table(
        "crawl_cache",
        sa.Column("url_hash", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("raw_html", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("next_recrawl_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("url_hash"),
    )

    op.create_table(
        "suppression_list",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("value_type", "value", name="idx_suppression_value"),
    )


def downgrade() -> None:
    op.drop_table("suppression_list")
    op.drop_table("crawl_cache")
    op.drop_table("contact_emails")
    op.drop_table("contacts")
    op.drop_index("idx_companies_norm_name", "companies")
    op.drop_index("idx_companies_phone", "companies")
    op.drop_index("idx_companies_domain", "companies")
    op.drop_table("companies")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
