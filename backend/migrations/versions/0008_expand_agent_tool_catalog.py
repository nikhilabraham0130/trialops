"""Permit the two clinical tools added after the original ALT-only agent plan.

Revision ID: 0008_agent_tools
Revises: 0007_interpretation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_agent_tools"
down_revision: str | Sequence[str] | None = "0007_interpretation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK_NAME = "ck_agent_plan_approved_tool_name"


def upgrade() -> None:
    """Expand only the allowed tool values, preserving every existing plan."""
    op.drop_constraint(op.f(CHECK_NAME), "agent_plan", type_="check")
    op.create_check_constraint(
        "approved_tool_name",
        "agent_plan",
        "tool_name IN ("
        "'calculate_alt_gt_3x_uln', "
        "'compare_severe_ae_incidence', "
        "'get_subject_safety_summary'"
        ")",
    )


def downgrade() -> None:
    """Refuse to shrink the constraint while newer-tool plans still exist."""
    newer_plan_count = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM agent_plan WHERE tool_name <> 'calculate_alt_gt_3x_uln'")
    )
    if newer_plan_count:
        raise RuntimeError(
            "Cannot downgrade the tool catalog while severe-AE or subject-safety plans exist."
        )
    op.drop_constraint(op.f(CHECK_NAME), "agent_plan", type_="check")
    op.create_check_constraint(
        "approved_tool_name",
        "agent_plan",
        "tool_name = 'calculate_alt_gt_3x_uln'",
    )
