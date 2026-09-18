"""Create dataset-versioned adverse-event storage.

Revision ID: 0003_ae_event
Revises: 0002_dm_subject
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_ae_event"
down_revision: str | Sequence[str] | None = "0002_dm_subject"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create AE rows with a same-version foreign key to DM subjects."""
    op.create_table(
        "ae_event",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_record_number", sa.Integer(), nullable=False),
        sa.Column("unique_subject_id", sa.String(), nullable=False),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("reported_term", sa.String(), nullable=False),
        sa.Column("preferred_term", sa.String(), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "MILD",
                "MODERATE",
                "SEVERE",
                name="adverse_event_severity",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("serious_flag", sa.String(length=1), nullable=False),
        sa.Column("start_date_text", sa.String(), nullable=False),
        sa.Column("end_date_text", sa.String(), nullable=True),
        sa.CheckConstraint("source_record_number > 0", name="positive_source_record_number"),
        sa.CheckConstraint("event_sequence > 0", name="positive_event_sequence"),
        sa.CheckConstraint("btrim(unique_subject_id) <> ''", name="nonempty_unique_subject_id"),
        sa.CheckConstraint("btrim(start_date_text) <> ''", name="nonempty_start_date_text"),
        sa.CheckConstraint("serious_flag IN ('Y', 'N')", name="serious_flag_values"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id", "unique_subject_id"],
            ["dm_subject.dataset_version_id", "dm_subject.unique_subject_id"],
            name="fk_ae_event_dataset_subject_dm_subject",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ae_event"),
        sa.UniqueConstraint(
            "dataset_version_id",
            "source_record_number",
            name="uq_ae_event_dataset_record_number",
        ),
        sa.UniqueConstraint(
            "dataset_version_id",
            "unique_subject_id",
            "event_sequence",
            name="uq_ae_event_dataset_subject_sequence",
        ),
    )
    op.create_index(
        "ix_ae_event_dataset_version_id",
        "ae_event",
        ["dataset_version_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the adverse-event table without changing DM or the catalog."""
    op.drop_index("ix_ae_event_dataset_version_id", table_name="ae_event")
    op.drop_table("ae_event")
