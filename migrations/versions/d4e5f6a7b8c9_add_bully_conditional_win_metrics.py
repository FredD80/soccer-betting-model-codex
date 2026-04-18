"""add bully conditional win metrics

Revision ID: d4e5f6a7b8c9
Revises: c1b2d3e4f5a6
Create Date: 2026-04-17 18:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c1b2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("backtest_runs", sa.Column("two_plus_given_win_rate", sa.Float(), nullable=True))
    op.add_column("backtest_runs", sa.Column("clean_sheet_given_win_rate", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("backtest_runs", "clean_sheet_given_win_rate")
    op.drop_column("backtest_runs", "two_plus_given_win_rate")
