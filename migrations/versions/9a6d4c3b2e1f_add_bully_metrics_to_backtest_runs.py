"""add bully metrics to backtest_runs

Revision ID: 9a6d4c3b2e1f
Revises: 5e1f7c9a2b4d
Create Date: 2026-04-17 14:15:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9a6d4c3b2e1f"
down_revision: Union[str, Sequence[str], None] = "5e1f7c9a2b4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("backtest_runs", sa.Column("two_plus_hit_rate", sa.Float(), nullable=True))
    op.add_column("backtest_runs", sa.Column("clean_sheet_hit_rate", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("backtest_runs", "clean_sheet_hit_rate")
    op.drop_column("backtest_runs", "two_plus_hit_rate")
