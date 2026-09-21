"""Store deterministic results for executed agent plans.

Revision ID: 0006_plan_result
Revises: 0005_agent_plan
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_plan_result"
down_revision: str | Sequence[str] | None = "0005_agent_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Retain the exact deterministic output and execution time."""
    op.add_column(
        "agent_plan",
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "agent_plan",
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove stored outputs while retaining the original proposed plans."""
    op.drop_column("agent_plan", "executed_at")
    op.drop_column("agent_plan", "result")
