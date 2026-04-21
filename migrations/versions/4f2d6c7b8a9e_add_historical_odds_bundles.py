"""add_historical_odds_bundles

Revision ID: 4f2d6c7b8a9e
Revises: 3b9e4f12a7c1
Create Date: 2026-04-20 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4f2d6c7b8a9e"
down_revision: Union[str, Sequence[str], None] = "3b9e4f12a7c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "historical_odds_bundles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fixture_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_fixture_id", sa.Integer(), nullable=False),
        sa.Column("competition_id", sa.Integer(), nullable=True),
        sa.Column("season_id", sa.Integer(), nullable=True),
        sa.Column("bookmaker_id", sa.Integer(), nullable=False),
        sa.Column("bookmaker_name", sa.String(), nullable=False),
        sa.Column("odds_type", sa.String(), nullable=False),
        sa.Column("home_odds", sa.Float(), nullable=True),
        sa.Column("draw_odds", sa.Float(), nullable=True),
        sa.Column("away_odds", sa.Float(), nullable=True),
        sa.Column("home_team_total_1_5_over_odds", sa.Float(), nullable=True),
        sa.Column("home_team_total_1_5_under_odds", sa.Float(), nullable=True),
        sa.Column("away_team_total_1_5_over_odds", sa.Float(), nullable=True),
        sa.Column("away_team_total_1_5_under_odds", sa.Float(), nullable=True),
        sa.Column("home_win_and_home_over_1_5_odds", sa.Float(), nullable=True),
        sa.Column("away_win_and_away_over_1_5_odds", sa.Float(), nullable=True),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source",
            "source_fixture_id",
            "bookmaker_id",
            "odds_type",
            name="uq_historical_odds_bundle_source_fixture_bookmaker_type",
        ),
    )


def downgrade() -> None:
    op.drop_table("historical_odds_bundles")
