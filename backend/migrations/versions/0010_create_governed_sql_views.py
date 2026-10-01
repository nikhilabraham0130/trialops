"""Expose version-filtered clinical views to a restricted SQL reader role.

Revision ID: 0010_sql_views
Revises: 0009_reproduction
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_sql_views"
down_revision: str | Sequence[str] | None = "0009_reproduction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create only the columns approved for analytical SQL access."""
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'trialops_reader') THEN "
        "CREATE ROLE trialops_reader NOLOGIN; "
        "END IF; END $$"
    )
    op.execute("GRANT trialops_reader TO CURRENT_USER")
    op.execute("GRANT USAGE ON SCHEMA public TO trialops_reader")
    op.execute(
        "CREATE VIEW vw_subjects WITH (security_barrier=true) AS "
        "SELECT dataset_version_id, unique_subject_id, age, sex, actual_arm "
        "FROM dm_subject "
        "WHERE dataset_version_id = current_setting('trialops.dataset_version_id', true)::uuid"
    )
    op.execute(
        "CREATE VIEW vw_adverse_events WITH (security_barrier=true) AS "
        "SELECT dataset_version_id, unique_subject_id, event_sequence, preferred_term, "
        "severity, serious_flag, start_date_text "
        "FROM ae_event "
        "WHERE dataset_version_id = current_setting('trialops.dataset_version_id', true)::uuid"
    )
    op.execute(
        "CREATE VIEW vw_laboratory_results WITH (security_barrier=true) AS "
        "SELECT dataset_version_id, unique_subject_id, result_sequence, test_code, "
        "standard_result, standard_unit, lower_reference_limit, upper_reference_limit, "
        "range_indicator, baseline_flag, observed_at_text "
        "FROM lb_result "
        "WHERE dataset_version_id = current_setting('trialops.dataset_version_id', true)::uuid"
    )
    op.execute(
        "GRANT SELECT ON vw_subjects, vw_adverse_events, vw_laboratory_results TO trialops_reader"
    )


def downgrade() -> None:
    """Remove only the views and role installed by this migration."""
    op.execute("DROP VIEW vw_laboratory_results")
    op.execute("DROP VIEW vw_adverse_events")
    op.execute("DROP VIEW vw_subjects")
    op.execute("REVOKE trialops_reader FROM CURRENT_USER")
    op.execute("DROP ROLE trialops_reader")
