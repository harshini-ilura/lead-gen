"""crawl_cache company_id + content_type

Revision ID: 003
Revises: 002
Create Date: 2026-06-07 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crawl_cache", sa.Column("company_id", sa.BigInteger(), nullable=True))
    op.add_column("crawl_cache", sa.Column("content_type", sa.Text(), nullable=True))
    op.create_index("idx_crawl_cache_company", "crawl_cache", ["company_id"])


def downgrade() -> None:
    op.drop_index("idx_crawl_cache_company", "crawl_cache")
    op.drop_column("crawl_cache", "content_type")
    op.drop_column("crawl_cache", "company_id")
