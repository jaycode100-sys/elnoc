"""Initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-11-01 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Note: Most tables are created by SQLAlchemy's create_all() at startup.
    # This migration only adds tables that are NOT created by create_all,
    # such as shift_close which was added after initial deployment.
    op.create_table(
        "shift_close",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("engineer", sa.String(length=200), nullable=False, default=""),
        sa.Column("shift_date", sa.String(length=20), nullable=False, default=""),
        sa.Column("shift", sa.String(length=20), nullable=False, default="day"),
        sa.Column("power_report_id", sa.Integer(), nullable=True),
        sa.Column("nothing_to_report", sa.Boolean(), nullable=False, default=False),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_shift_close_engineer"), "shift_close", ["engineer"], unique=False)
    op.create_index(op.f("ix_shift_close_shift_date"), "shift_close", ["shift_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_shift_close_shift_date"), table_name="shift_close")
    op.drop_index(op.f("ix_shift_close_engineer"), table_name="shift_close")
    op.drop_table("shift_close")
