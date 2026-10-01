"""Add local independent review state and append-only business event tables.

Revision ID: 0011_review_audit
Revises: 0010_sql_views
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_review_audit"
down_revision: str | Sequence[str] | None = "0010_sql_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_plan",
        sa.Column("review_state", sa.String(length=32), server_default="DRAFT", nullable=False),
    )
    op.add_column("agent_plan", sa.Column("submitted_by", sa.String(length=128), nullable=True))
    op.add_column(
        "agent_plan", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "valid_review_state",
        "agent_plan",
        "review_state IN ('DRAFT', 'PENDING_REVIEW', 'APPROVED', 'CHANGES_REQUESTED', 'REJECTED')",
    )
    op.create_check_constraint(
        "submission_fields_together",
        "agent_plan",
        "(submitted_by IS NULL AND submitted_at IS NULL) OR "
        "(submitted_by IS NOT NULL AND submitted_at IS NOT NULL)",
    )
    op.create_table(
        "review_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("agent_plan.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("comment", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "action IN ('SUBMITTED', 'APPROVED', 'CHANGES_REQUESTED', 'REJECTED')",
            name="valid_action",
        ),
        sa.CheckConstraint("btrim(actor_id) <> ''", name="nonempty_actor_id"),
    )
    op.create_index("ix_review_event_plan_id", "review_event", ["plan_id"])
    op.create_table(
        "audit_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("btrim(actor_id) <> ''", name="nonempty_actor_id"),
    )
    op.create_index("ix_audit_event_entity_id", "audit_event", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_event_entity_id", table_name="audit_event")
    op.drop_table("audit_event")
    op.drop_index("ix_review_event_plan_id", table_name="review_event")
    op.drop_table("review_event")
    op.drop_constraint("submission_fields_together", "agent_plan", type_="check")
    op.drop_constraint("valid_review_state", "agent_plan", type_="check")
    op.drop_column("agent_plan", "submitted_at")
    op.drop_column("agent_plan", "submitted_by")
    op.drop_column("agent_plan", "review_state")
