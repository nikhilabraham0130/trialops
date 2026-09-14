"""Create normalized demographics subject storage.

Revision ID: 0002_dm_subject
Revises: 0001_dataset_catalog
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_dm_subject"
down_revision: str | Sequence[str] | None = "0001_dataset_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the dataset-versioned DM subject table."""
    op.create_table(
        "dm_subject",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_record_number", sa.Integer(), nullable=False),
        sa.Column("unique_subject_id", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("age_unit", sa.String(), nullable=False),
        sa.Column("sex", sa.String(), nullable=False),
        sa.Column("race", sa.String(), nullable=False),
        sa.Column("planned_arm", sa.String(), nullable=False),
        sa.Column("actual_arm", sa.String(), nullable=False),
        sa.CheckConstraint("source_record_number > 0", name="positive_source_record_number"),
        sa.CheckConstraint("age BETWEEN 0 AND 130", name="age_range"),
        sa.CheckConstraint("btrim(unique_subject_id) <> ''", name="nonempty_unique_subject_id"),
        sa.CheckConstraint("btrim(subject_id) <> ''", name="nonempty_subject_id"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_version.id"],
            name="fk_dm_subject_dataset_version_id_dataset_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dm_subject"),
        sa.UniqueConstraint(
            "dataset_version_id",
            "source_record_number",
            name="uq_dm_subject_dataset_record_number",
        ),
        sa.UniqueConstraint(
            "dataset_version_id",
            "unique_subject_id",
            name="uq_dm_subject_dataset_unique_subject",
        ),
    )
    op.create_index(
        "ix_dm_subject_dataset_version_id",
        "dm_subject",
        ["dataset_version_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove normalized demographics subject storage."""
    op.drop_index("ix_dm_subject_dataset_version_id", table_name="dm_subject")
    op.drop_table("dm_subject")
