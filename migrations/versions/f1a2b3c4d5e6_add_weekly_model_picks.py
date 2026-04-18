"""add weekly model picks

Revision ID: f1a2b3c4d5e6
Revises: e6f7a8b9c0d1
Create Date: 2026-04-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "weekly_model_picks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("season_key", sa.String(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("model_view", sa.String(), nullable=False),
        sa.Column("model_label", sa.String(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("fixture_id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=True),
        sa.Column("market_type", sa.String(), nullable=False),
        sa.Column("selection", sa.String(), nullable=False),
        sa.Column("line", sa.Float(), nullable=True),
        sa.Column("decimal_odds", sa.Float(), nullable=True),
        sa.Column("american_odds", sa.Integer(), nullable=True),
        sa.Column("model_probability", sa.Float(), nullable=True),
        sa.Column("final_probability", sa.Float(), nullable=True),
        sa.Column("edge_pct", sa.Float(), nullable=True),
        sa.Column("confidence_tier", sa.String(), nullable=True),
        sa.Column("result_status", sa.String(), nullable=False, server_default="open"),
        sa.Column("profit_units", sa.Float(), nullable=True),
        sa.Column("graded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"]),
        sa.ForeignKeyConstraint(["model_id"], ["models.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("season_key", "week_start", "model_view", "rank", name="uq_weekly_model_picks_slot"),
    )


def downgrade():
    op.drop_table("weekly_model_picks")
