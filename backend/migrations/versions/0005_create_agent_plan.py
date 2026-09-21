"""Create persistent confirmation-required agent plans.

Revision ID: 0005_agent_plan
Revises: 0004_lb_result
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_agent_plan"
down_revision: str | Sequence[str] | None = "0004_lb_result"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store the exact plan that will later be confirmed and executed."""
    op.create_table(
        "agent_plan",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.String(length=2000), nullable=False),
        sa.Column("purpose", sa.String(length=2000), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "AWAITING_CONFIRMATION",
                "EXECUTING",
                "EXECUTED",
                "FAILED",
                name="agent_plan_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "tool_name",
            sa.Enum(
                "calculate_alt_gt_3x_uln",
                name="approved_tool_name",
                native_enum=False,
                create_constraint=True,
                length=64,
            ),
            nullable=False,
        ),
        sa.Column("tool_arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("btrim(question) <> ''", name="nonempty_question"),
        sa.CheckConstraint("btrim(purpose) <> ''", name="nonempty_purpose"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_version.id"],
            name="fk_agent_plan_dataset_version_id_dataset_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_plan"),
    )
    op.create_index(
        "ix_agent_plan_dataset_version_id",
        "agent_plan",
        ["dataset_version_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove stored plans without changing source or normalized clinical data."""
    op.drop_index("ix_agent_plan_dataset_version_id", table_name="agent_plan")
    op.drop_table("agent_plan")
