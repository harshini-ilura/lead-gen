"""discovery_areas seed table

Revision ID: 002
Revises: 001
Create Date: 2026-06-02 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_areas",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("area_name", sa.Text(), nullable=False),
        sa.Column("emirate", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), server_default="seed", nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_run_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_result_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("emirate", "area_name", name="idx_discovery_area_uniq"),
    )
    op.create_index(
        "idx_discovery_areas_active", "discovery_areas", ["emirate", "is_active"]
    )


def downgrade() -> None:
    op.drop_index("idx_discovery_areas_active", "discovery_areas")
    op.drop_table("discovery_areas")
