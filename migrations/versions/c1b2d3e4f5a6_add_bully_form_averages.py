"""add bully form averages

Revision ID: c1b2d3e4f5a6
Revises: 9a6d4c3b2e1f
Create Date: 2026-04-17 16:05:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1b2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "9a6d4c3b2e1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("elo_form_predictions", sa.Column("home_form_for_avg", sa.Float(), nullable=True))
    op.add_column("elo_form_predictions", sa.Column("home_form_against_avg", sa.Float(), nullable=True))
    op.add_column("elo_form_predictions", sa.Column("away_form_for_avg", sa.Float(), nullable=True))
    op.add_column("elo_form_predictions", sa.Column("away_form_against_avg", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("elo_form_predictions", "away_form_against_avg")
    op.drop_column("elo_form_predictions", "away_form_for_avg")
    op.drop_column("elo_form_predictions", "home_form_against_avg")
    op.drop_column("elo_form_predictions", "home_form_for_avg")
