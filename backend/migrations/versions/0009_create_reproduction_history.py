"""Store every deterministic reproduction comparison.

Revision ID: 0009_reproduction
Revises: 0008_agent_tools
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_reproduction"
down_revision: str | Sequence[str] | None = "0008_agent_tools"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create a history table linked to the original saved plan."""
    op.create_table(
        "reproduction_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stored_result_sha256", sa.String(length=64), nullable=False),
        sa.Column("reproduced_result_sha256", sa.String(length=64), nullable=False),
        sa.Column("difference_count", sa.Integer(), nullable=False),
        sa.Column("differences", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("differences_truncated", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('EXACT_MATCH', 'MISMATCH')", name="valid_status"),
        sa.CheckConstraint("difference_count >= 0", name="nonnegative_difference_count"),
        sa.CheckConstraint("stored_result_sha256 ~ '^[0-9a-f]{64}$'", name="stored_sha256"),
        sa.CheckConstraint("reproduced_result_sha256 ~ '^[0-9a-f]{64}$'", name="reproduced_sha256"),
        sa.CheckConstraint("jsonb_typeof(differences) = 'array'", name="differences_array"),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["agent_plan.id"],
            name="fk_reproduction_run_plan_id_agent_plan",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reproduction_run"),
    )
    op.create_index("ix_reproduction_run_plan_id", "reproduction_run", ["plan_id"])


def downgrade() -> None:
    """Drop stored history only when a rollback is intentionally requested."""
    op.drop_index("ix_reproduction_run_plan_id", table_name="reproduction_run")
    op.drop_table("reproduction_run")
