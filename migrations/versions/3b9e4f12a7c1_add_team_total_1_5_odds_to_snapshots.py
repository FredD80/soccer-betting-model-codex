"""add_team_total_1_5_odds_to_snapshots

Revision ID: 3b9e4f12a7c1
Revises: 6a4b0f8c9d1e
Create Date: 2026-04-19 22:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3b9e4f12a7c1"
down_revision: Union[str, Sequence[str], None] = "6a4b0f8c9d1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("odds_snapshots", sa.Column("home_team_total_1_5_over_odds", sa.Float(), nullable=True))
    op.add_column("odds_snapshots", sa.Column("home_team_total_1_5_under_odds", sa.Float(), nullable=True))
    op.add_column("odds_snapshots", sa.Column("away_team_total_1_5_over_odds", sa.Float(), nullable=True))
    op.add_column("odds_snapshots", sa.Column("away_team_total_1_5_under_odds", sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("odds_snapshots", "away_team_total_1_5_under_odds")
    op.drop_column("odds_snapshots", "away_team_total_1_5_over_odds")
    op.drop_column("odds_snapshots", "home_team_total_1_5_under_odds")
    op.drop_column("odds_snapshots", "home_team_total_1_5_over_odds")
