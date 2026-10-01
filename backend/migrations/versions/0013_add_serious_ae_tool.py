"""Permit serious-AE plans without changing earlier saved analyses.

Revision ID: 0013_serious_ae
Revises: 0012_history_guard
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_serious_ae"
down_revision: str | Sequence[str] | None = "0012_history_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK_NAME = "ck_agent_plan_approved_tool_name"


def upgrade() -> None:
    op.drop_constraint(op.f(CHECK_NAME), "agent_plan", type_="check")
    op.create_check_constraint(
        "approved_tool_name",
        "agent_plan",
        "tool_name IN ("
        "'calculate_alt_gt_3x_uln', "
        "'compare_severe_ae_incidence', "
        "'compare_serious_ae_incidence', "
        "'get_subject_safety_summary'"
        ")",
    )


def downgrade() -> None:
    serious_plan_count = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM agent_plan WHERE tool_name = 'compare_serious_ae_incidence'")
    )
    if serious_plan_count:
        raise RuntimeError("Cannot downgrade while serious-AE analysis plans exist.")
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
