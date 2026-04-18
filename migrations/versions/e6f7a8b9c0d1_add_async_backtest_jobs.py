"""add async backtest jobs

Revision ID: e6f7a8b9c0d1
Revises: d4e5f6a7b8c9
Create Date: 2026-04-17 20:25:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backtest_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("requested_markets", sa.Text(), nullable=False),
        sa.Column("date_from", sa.DateTime(), nullable=False),
        sa.Column("date_to", sa.DateTime(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("backtest_runs", sa.Column("backtest_job_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_backtest_runs_backtest_job_id",
        "backtest_runs",
        "backtest_jobs",
        ["backtest_job_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_backtest_runs_backtest_job_id", "backtest_runs", type_="foreignkey")
    op.drop_column("backtest_runs", "backtest_job_id")
    op.drop_table("backtest_jobs")
