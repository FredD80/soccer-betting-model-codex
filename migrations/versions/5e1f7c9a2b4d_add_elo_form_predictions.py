"""add elo_form_predictions

Revision ID: 5e1f7c9a2b4d
Revises: 1c9d4b7e2f6a
Create Date: 2026-04-17 09:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5e1f7c9a2b4d"
down_revision: Union[str, Sequence[str], None] = "1c9d4b7e2f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "elo_form_predictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("fixture_id", sa.Integer(), nullable=False),
        sa.Column("favorite_side", sa.String(), nullable=False),
        sa.Column("elo_gap", sa.Float(), nullable=False),
        sa.Column("is_bully_spot", sa.Boolean(), nullable=False),
        sa.Column("home_elo", sa.Float(), nullable=False),
        sa.Column("away_elo", sa.Float(), nullable=False),
        sa.Column("home_xg_diff_avg", sa.Float(), nullable=True),
        sa.Column("away_xg_diff_avg", sa.Float(), nullable=True),
        sa.Column("home_xg_trend", sa.Float(), nullable=True),
        sa.Column("away_xg_trend", sa.Float(), nullable=True),
        sa.Column("home_xg_matches_used", sa.Integer(), nullable=False),
        sa.Column("away_xg_matches_used", sa.Integer(), nullable=False),
        sa.Column("trend_adjustment", sa.Float(), nullable=False),
        sa.Column("home_probability", sa.Float(), nullable=False),
        sa.Column("draw_probability", sa.Float(), nullable=False),
        sa.Column("away_probability", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"]),
        sa.ForeignKeyConstraint(["model_id"], ["models.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_id", "fixture_id", name="uq_elo_form_predictions_model_fixture"),
    )


def downgrade() -> None:
    op.drop_table("elo_form_predictions")
