"""add moneyline_predictions table

Revision ID: a1b2c3d4e5f6
Revises: 2aab01d56d30
Create Date: 2026-04-14 22:47:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '2aab01d56d30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'moneyline_predictions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('model_id', sa.Integer(), sa.ForeignKey('models.id'), nullable=False),
        sa.Column('fixture_id', sa.Integer(), sa.ForeignKey('fixtures.id'), nullable=False),
        sa.Column('outcome', sa.String(), nullable=False),
        sa.Column('probability', sa.Float()),
        sa.Column('ev_score', sa.Float()),
        sa.Column('confidence_tier', sa.String()),
        sa.Column('final_probability', sa.Float()),
        sa.Column('edge_pct', sa.Float()),
        sa.Column('kelly_fraction', sa.Float()),
        sa.Column('steam_downgraded', sa.Boolean(), server_default=sa.false()),
        sa.Column('created_at', sa.DateTime()),
    )
    op.create_index(
        'ix_moneyline_predictions_model_fixture_outcome',
        'moneyline_predictions',
        ['model_id', 'fixture_id', 'outcome'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_moneyline_predictions_model_fixture_outcome', table_name='moneyline_predictions')
    op.drop_table('moneyline_predictions')
