"""Create the study and dataset source catalog.

Revision ID: 0001_dataset_catalog
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_dataset_catalog"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the foundational dataset catalog tables."""
    op.create_table(
        "study",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("study_oid", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_study"),
        sa.UniqueConstraint("study_oid", name="uq_study_study_oid"),
    )

    op.create_table(
        "dataset_version",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("version_label", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "RECEIVED",
                "VALIDATING",
                "VALID",
                "VALID_WITH_WARNINGS",
                "BLOCKED",
                name="dataset_version_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="RECEIVED",
            nullable=False,
        ),
        sa.Column("source_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("combined_checksum", sa.String(length=64), nullable=False),
        sa.Column("validation_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "combined_checksum ~ '^[0-9a-f]{64}$'",
            name="combined_checksum_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["study.id"],
            name="fk_dataset_version_study_id_study",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dataset_version"),
        sa.UniqueConstraint(
            "study_id",
            "combined_checksum",
            name="uq_dataset_version_study_checksum",
        ),
        sa.UniqueConstraint(
            "study_id",
            "version_label",
            name="uq_dataset_version_study_version_label",
        ),
    )
    op.create_index(
        "ix_dataset_version_study_id",
        "dataset_version",
        ["study_id"],
        unique=False,
    )

    op.create_table(
        "source_artifact",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "dataset-json",
                "define-xml",
                name="artifact_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("domain", sa.String(length=8), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("byte_size > 0", name="positive_byte_size"),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="sha256",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_version.id"],
            name="fk_source_artifact_dataset_version_id_dataset_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_artifact"),
        sa.UniqueConstraint(
            "dataset_version_id",
            "filename",
            name="uq_source_artifact_dataset_filename",
        ),
    )
    op.create_index(
        "ix_source_artifact_dataset_version_id",
        "source_artifact",
        ["dataset_version_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the foundational dataset catalog tables."""
    op.drop_index("ix_source_artifact_dataset_version_id", table_name="source_artifact")
    op.drop_table("source_artifact")
    op.drop_index("ix_dataset_version_study_id", table_name="dataset_version")
    op.drop_table("dataset_version")
    op.drop_table("study")
