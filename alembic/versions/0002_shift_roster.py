"""Add shift_roster table

Revision ID: 0002_shift_roster
Revises: 0001_initial
Create Date: 2026-11-04 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_shift_roster"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shift_roster",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("engineer", sa.String(length=200), nullable=False, default="", index=True),
        sa.Column("shift_date", sa.String(length=20), nullable=False, default="", index=True),
        sa.Column("shift", sa.String(length=20), nullable=False, default="day"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_shift_roster_engineer"), "shift_roster", ["engineer"], unique=False)
    op.create_index(op.f("ix_shift_roster_shift_date"), "shift_roster", ["shift_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_shift_roster_shift_date"), table_name="shift_roster")
    op.drop_index(op.f("ix_shift_roster_engineer"), table_name="shift_roster")
    op.drop_table("shift_roster")
