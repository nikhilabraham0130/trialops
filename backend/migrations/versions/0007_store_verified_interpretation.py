"""Store numerically verified AI interpretations.

Revision ID: 0007_interpretation
Revises: 0006_plan_result
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_interpretation"
down_revision: str | Sequence[str] | None = "0006_plan_result"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Retain one complete verified interpretation as structured JSON."""
    op.add_column(
        "agent_plan",
        sa.Column(
            "interpretation",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "interpretation_is_object",
        "agent_plan",
        "interpretation IS NULL OR jsonb_typeof(interpretation) = 'object'",
    )


def downgrade() -> None:
    """Remove verified interpretations without changing deterministic results."""
    op.drop_constraint(
        "ck_agent_plan_interpretation_is_object",
        "agent_plan",
        type_="check",
    )
    op.drop_column("agent_plan", "interpretation")
