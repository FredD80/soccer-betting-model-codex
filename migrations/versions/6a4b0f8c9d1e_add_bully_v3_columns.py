"""add bully v3 columns

Revision ID: 6a4b0f8c9d1e
Revises: f1a2b3c4d5e6
Create Date: 2026-04-19 03:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6a4b0f8c9d1e"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("elo_form_predictions", sa.Column("p_joint", sa.Float(), nullable=True))
    op.add_column("elo_form_predictions", sa.Column("p_joint_raw", sa.Float(), nullable=True))
    op.add_column("elo_form_predictions", sa.Column("lambda_favorite", sa.Float(), nullable=True))
    op.add_column("elo_form_predictions", sa.Column("lambda_underdog", sa.Float(), nullable=True))
    op.add_column("elo_form_predictions", sa.Column("market_source", sa.String(), nullable=True))
    op.add_column("elo_form_predictions", sa.Column("gate_summary", sa.Text(), nullable=True))
    op.add_column(
        "elo_form_predictions",
        sa.Column("research_mode_active", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("elo_form_predictions", "research_mode_active")
    op.drop_column("elo_form_predictions", "gate_summary")
    op.drop_column("elo_form_predictions", "market_source")
    op.drop_column("elo_form_predictions", "lambda_underdog")
    op.drop_column("elo_form_predictions", "lambda_favorite")
    op.drop_column("elo_form_predictions", "p_joint_raw")
    op.drop_column("elo_form_predictions", "p_joint")
