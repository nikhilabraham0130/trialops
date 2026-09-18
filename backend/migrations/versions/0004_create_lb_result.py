"""Create dataset-versioned laboratory-result storage.

Revision ID: 0004_lb_result
Revises: 0003_ae_event
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_lb_result"
down_revision: str | Sequence[str] | None = "0003_ae_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create LB rows with nullable measurements and same-version DM linkage."""
    op.create_table(
        "lb_result",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_record_number", sa.Integer(), nullable=False),
        sa.Column("unique_subject_id", sa.String(), nullable=False),
        sa.Column("result_sequence", sa.Integer(), nullable=False),
        sa.Column("test_code", sa.String(), nullable=False),
        sa.Column("test_name", sa.String(), nullable=False),
        sa.Column("standard_result", sa.Numeric(), nullable=True),
        sa.Column("standard_unit", sa.String(), nullable=True),
        sa.Column("lower_reference_limit", sa.Numeric(), nullable=True),
        sa.Column("upper_reference_limit", sa.Numeric(), nullable=True),
        sa.Column(
            "range_indicator",
            sa.Enum(
                "NORMAL",
                "LOW",
                "HIGH",
                "ABNORMAL",
                name="lb_normal_range_indicator",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=True,
        ),
        sa.Column("baseline_flag", sa.String(length=1), nullable=True),
        sa.Column("observed_at_text", sa.String(), nullable=False),
        sa.CheckConstraint("source_record_number > 0", name="positive_source_record_number"),
        sa.CheckConstraint("result_sequence > 0", name="positive_result_sequence"),
        sa.CheckConstraint("btrim(unique_subject_id) <> ''", name="nonempty_unique_subject_id"),
        sa.CheckConstraint("btrim(test_code) <> ''", name="nonempty_test_code"),
        sa.CheckConstraint("btrim(observed_at_text) <> ''", name="nonempty_observed_at_text"),
        sa.CheckConstraint("baseline_flag = 'Y'", name="baseline_flag_value"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id", "unique_subject_id"],
            ["dm_subject.dataset_version_id", "dm_subject.unique_subject_id"],
            name="fk_lb_result_dataset_subject_dm_subject",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_lb_result"),
        sa.UniqueConstraint(
            "dataset_version_id",
            "source_record_number",
            name="uq_lb_result_dataset_record_number",
        ),
        sa.UniqueConstraint(
            "dataset_version_id",
            "unique_subject_id",
            "result_sequence",
            name="uq_lb_result_dataset_subject_sequence",
        ),
    )
    op.create_index(
        "ix_lb_result_dataset_version_id",
        "lb_result",
        ["dataset_version_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove laboratory rows without changing DM, AE, or the source catalog."""
    op.drop_index("ix_lb_result_dataset_version_id", table_name="lb_result")
    op.drop_table("lb_result")
