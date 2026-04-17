"""add manual_picks

Revision ID: 1c9d4b7e2f6a
Revises: 7f2b8c1d4e9a
Create Date: 2026-04-16 00:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1c9d4b7e2f6a"
down_revision: Union[str, Sequence[str], None] = "7f2b8c1d4e9a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "manual_picks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fixture_id", sa.Integer(), nullable=False),
        sa.Column("market_type", sa.String(), nullable=False),
        sa.Column("selection", sa.String(), nullable=False),
        sa.Column("line", sa.Float(), nullable=True),
        sa.Column("decimal_odds", sa.Float(), nullable=True),
        sa.Column("american_odds", sa.Integer(), nullable=True),
        sa.Column("stake_units", sa.Float(), nullable=False),
        sa.Column("bookmaker", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("result_status", sa.String(), nullable=False),
        sa.Column("profit_units", sa.Float(), nullable=True),
        sa.Column("graded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("manual_picks")
