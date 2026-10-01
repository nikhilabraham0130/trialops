"""Reject accidental updates or deletes of audit and review history.

Revision ID: 0012_history_guard
Revises: 0011_review_audit
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_history_guard"
down_revision: str | Sequence[str] | None = "0011_review_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE FUNCTION trialops_reject_history_mutation() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'History records are append-only' USING ERRCODE = '55000'; "
        "END; $$"
    )
    for table_name in ("audit_event", "review_event", "reproduction_run"):
        op.execute(
            f"CREATE TRIGGER {table_name}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION trialops_reject_history_mutation()"
        )


def downgrade() -> None:
    for table_name in ("reproduction_run", "review_event", "audit_event"):
        op.execute(f"DROP TRIGGER {table_name}_append_only ON {table_name}")
    op.execute("DROP FUNCTION trialops_reject_history_mutation()")
