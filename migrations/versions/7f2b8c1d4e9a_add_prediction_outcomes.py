"""add prediction_outcomes and snapshot refs for live picks

Revision ID: 7f2b8c1d4e9a
Revises: 43b3e8665768, a1b2c3d4e5f6
Create Date: 2026-04-16 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7f2b8c1d4e9a"
down_revision: Union[str, Sequence[str], None] = ("43b3e8665768", "a1b2c3d4e5f6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "spread_predictions",
        sa.Column("odds_snapshot_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ou_analysis",
        sa.Column("odds_snapshot_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "moneyline_predictions",
        sa.Column("odds_snapshot_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_spread_predictions_odds_snapshot_id",
        "spread_predictions",
        "odds_snapshots",
        ["odds_snapshot_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_ou_analysis_odds_snapshot_id",
        "ou_analysis",
        "odds_snapshots",
        ["odds_snapshot_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_moneyline_predictions_odds_snapshot_id",
        "moneyline_predictions",
        "odds_snapshots",
        ["odds_snapshot_id"],
        ["id"],
    )

    op.create_table(
        "prediction_outcomes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fixture_id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("market_type", sa.String(), nullable=False),
        sa.Column("prediction_row_id", sa.Integer(), nullable=False),
        sa.Column("selection", sa.String(), nullable=False),
        sa.Column("line", sa.Float(), nullable=True),
        sa.Column("decimal_odds", sa.Float(), nullable=True),
        sa.Column("american_odds", sa.Integer(), nullable=True),
        sa.Column("model_probability", sa.Float(), nullable=True),
        sa.Column("final_probability", sa.Float(), nullable=True),
        sa.Column("edge_pct", sa.Float(), nullable=True),
        sa.Column("kelly_fraction", sa.Float(), nullable=True),
        sa.Column("confidence_tier", sa.String(), nullable=True),
        sa.Column("result_status", sa.String(), nullable=False),
        sa.Column("profit_units", sa.Float(), nullable=True),
        sa.Column("graded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"]),
        sa.ForeignKeyConstraint(["model_id"], ["models.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("market_type", "prediction_row_id", name="uq_prediction_outcomes_market_row"),
    )


def downgrade() -> None:
    op.drop_table("prediction_outcomes")
    op.drop_constraint("fk_moneyline_predictions_odds_snapshot_id", "moneyline_predictions", type_="foreignkey")
    op.drop_constraint("fk_ou_analysis_odds_snapshot_id", "ou_analysis", type_="foreignkey")
    op.drop_constraint("fk_spread_predictions_odds_snapshot_id", "spread_predictions", type_="foreignkey")
    op.drop_column("moneyline_predictions", "odds_snapshot_id")
    op.drop_column("ou_analysis", "odds_snapshot_id")
    op.drop_column("spread_predictions", "odds_snapshot_id")
