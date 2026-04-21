"""add_favorite_sgp_backtest_rows

Revision ID: 8d7c6b5a4e3f
Revises: 4f2d6c7b8a9e
Create Date: 2026-04-20 17:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8d7c6b5a4e3f"
down_revision: Union[str, Sequence[str], None] = "4f2d6c7b8a9e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "favorite_sgp_backtest_rows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("historical_bundle_id", sa.Integer(), nullable=False),
        sa.Column("fixture_id", sa.Integer(), nullable=False),
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("kickoff_at", sa.DateTime(), nullable=False),
        sa.Column("bookmaker_id", sa.Integer(), nullable=False),
        sa.Column("bookmaker_name", sa.String(), nullable=False),
        sa.Column("odds_type", sa.String(), nullable=False),
        sa.Column("favorite_side", sa.String(), nullable=False),
        sa.Column("favorite_team_id", sa.Integer(), nullable=False),
        sa.Column("favorite_team_name", sa.String(), nullable=False),
        sa.Column("underdog_team_id", sa.Integer(), nullable=False),
        sa.Column("underdog_team_name", sa.String(), nullable=False),
        sa.Column("favorite_ml_odds", sa.Float(), nullable=False),
        sa.Column("favorite_ml_american_odds", sa.Integer(), nullable=True),
        sa.Column("underdog_ml_odds", sa.Float(), nullable=False),
        sa.Column("underdog_ml_american_odds", sa.Integer(), nullable=True),
        sa.Column("draw_odds", sa.Float(), nullable=True),
        sa.Column("draw_american_odds", sa.Integer(), nullable=True),
        sa.Column("favorite_team_total_over_1_5_odds", sa.Float(), nullable=True),
        sa.Column("favorite_team_total_over_1_5_american_odds", sa.Integer(), nullable=True),
        sa.Column("favorite_team_total_under_1_5_odds", sa.Float(), nullable=True),
        sa.Column("favorite_team_total_under_1_5_american_odds", sa.Integer(), nullable=True),
        sa.Column("p_favorite_win_fair", sa.Float(), nullable=True),
        sa.Column("p_favorite_team_total_over_1_5_fair", sa.Float(), nullable=True),
        sa.Column("p_joint_fair_independent", sa.Float(), nullable=True),
        sa.Column("sgp_actual_odds", sa.Float(), nullable=True),
        sa.Column("sgp_actual_american_odds", sa.Integer(), nullable=True),
        sa.Column("sgp_synth_odds", sa.Float(), nullable=True),
        sa.Column("sgp_synth_american_odds", sa.Integer(), nullable=True),
        sa.Column("sgp_usable_odds", sa.Float(), nullable=True),
        sa.Column("sgp_usable_american_odds", sa.Integer(), nullable=True),
        sa.Column("favorite_won", sa.Boolean(), nullable=True),
        sa.Column("favorite_scored_2_plus", sa.Boolean(), nullable=True),
        sa.Column("favorite_ml_and_over_1_5_hit", sa.Boolean(), nullable=True),
        sa.Column("built_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"]),
        sa.ForeignKeyConstraint(["historical_bundle_id"], ["historical_odds_bundles.id"]),
        sa.ForeignKeyConstraint(["league_id"], ["leagues.id"]),
        sa.ForeignKeyConstraint(["favorite_team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["underdog_team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "historical_bundle_id",
            name="uq_favorite_sgp_backtest_rows_historical_bundle",
        ),
    )
    op.create_index(
        "ix_favorite_sgp_backtest_rows_fixture_id",
        "favorite_sgp_backtest_rows",
        ["fixture_id"],
    )
    op.create_index(
        "ix_favorite_sgp_backtest_rows_league_id",
        "favorite_sgp_backtest_rows",
        ["league_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_favorite_sgp_backtest_rows_league_id", table_name="favorite_sgp_backtest_rows")
    op.drop_index("ix_favorite_sgp_backtest_rows_fixture_id", table_name="favorite_sgp_backtest_rows")
    op.drop_table("favorite_sgp_backtest_rows")
