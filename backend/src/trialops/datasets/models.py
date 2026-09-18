"""Database models for versioned source datasets."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trialops.datasets.adverse_events import AdverseEventSeverity
from trialops.datasets.laboratory_results import NormalRangeIndicator
from trialops.datasets.manifest import ArtifactKind
from trialops.db.base import Base


class DatasetVersionStatus(StrEnum):
    """Lifecycle states for an immutable dataset snapshot."""

    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    VALID = "VALID"
    VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
    BLOCKED = "BLOCKED"


class DatasetVersion(Base):
    """One identified and checksummed snapshot of a study's source data."""

    __tablename__ = "dataset_version"
    __table_args__ = (
        CheckConstraint(
            "combined_checksum ~ '^[0-9a-f]{64}$'",
            name="combined_checksum_sha256",
        ),
        UniqueConstraint(
            "study_id",
            "combined_checksum",
            name="uq_dataset_version_study_checksum",
        ),
        UniqueConstraint(
            "study_id",
            "version_label",
            name="uq_dataset_version_study_version_label",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        default=uuid4,
        server_default=text("gen_random_uuid()"),
        primary_key=True,
    )
    study_id: Mapped[UUID] = mapped_column(
        ForeignKey("study.id", ondelete="RESTRICT"),
        index=True,
    )
    version_label: Mapped[str] = mapped_column(String(100))
    status: Mapped[DatasetVersionStatus] = mapped_column(
        Enum(
            DatasetVersionStatus,
            name="dataset_version_status",
            native_enum=False,
            create_constraint=True,
            length=32,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        default=DatasetVersionStatus.RECEIVED,
        server_default=DatasetVersionStatus.RECEIVED.value,
    )
    source_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    combined_checksum: Mapped[str] = mapped_column(String(64))
    validation_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class SourceArtifactRecord(Base):
    """Stored identity and integrity metadata for one original source file."""

    __tablename__ = "source_artifact"
    __table_args__ = (
        CheckConstraint("byte_size > 0", name="positive_byte_size"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256"),
        UniqueConstraint(
            "dataset_version_id",
            "filename",
            name="uq_source_artifact_dataset_filename",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        default=uuid4,
        server_default=text("gen_random_uuid()"),
        primary_key=True,
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"),
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255))
    kind: Mapped[ArtifactKind] = mapped_column(
        Enum(
            ArtifactKind,
            name="artifact_kind",
            native_enum=False,
            create_constraint=True,
            length=32,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        )
    )
    domain: Mapped[str | None] = mapped_column(String(8), nullable=True)
    byte_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class DMSubject(Base):
    """One normalized demographics record within an immutable dataset version."""

    __tablename__ = "dm_subject"
    __table_args__ = (
        CheckConstraint("source_record_number > 0", name="positive_source_record_number"),
        CheckConstraint("age BETWEEN 0 AND 130", name="age_range"),
        CheckConstraint("btrim(unique_subject_id) <> ''", name="nonempty_unique_subject_id"),
        CheckConstraint("btrim(subject_id) <> ''", name="nonempty_subject_id"),
        UniqueConstraint(
            "dataset_version_id",
            "source_record_number",
            name="uq_dm_subject_dataset_record_number",
        ),
        UniqueConstraint(
            "dataset_version_id",
            "unique_subject_id",
            name="uq_dm_subject_dataset_unique_subject",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        default=uuid4,
        server_default=text("gen_random_uuid()"),
        primary_key=True,
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"),
        index=True,
    )
    source_record_number: Mapped[int] = mapped_column(Integer)
    unique_subject_id: Mapped[str] = mapped_column(String)
    subject_id: Mapped[str] = mapped_column(String)
    age: Mapped[int] = mapped_column(Integer)
    age_unit: Mapped[str] = mapped_column(String)
    sex: Mapped[str] = mapped_column(String)
    race: Mapped[str] = mapped_column(String)
    planned_arm: Mapped[str] = mapped_column(String)
    actual_arm: Mapped[str] = mapped_column(String)


class AEEvent(Base):
    """One adverse event linked to a DM subject in the same dataset version."""

    __tablename__ = "ae_event"
    __table_args__ = (
        CheckConstraint("source_record_number > 0", name="positive_source_record_number"),
        CheckConstraint("event_sequence > 0", name="positive_event_sequence"),
        CheckConstraint("btrim(unique_subject_id) <> ''", name="nonempty_unique_subject_id"),
        CheckConstraint("btrim(start_date_text) <> ''", name="nonempty_start_date_text"),
        CheckConstraint("serious_flag IN ('Y', 'N')", name="serious_flag_values"),
        ForeignKeyConstraint(
            ["dataset_version_id", "unique_subject_id"],
            ["dm_subject.dataset_version_id", "dm_subject.unique_subject_id"],
            name="fk_ae_event_dataset_subject_dm_subject",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "dataset_version_id",
            "source_record_number",
            name="uq_ae_event_dataset_record_number",
        ),
        UniqueConstraint(
            "dataset_version_id",
            "unique_subject_id",
            "event_sequence",
            name="uq_ae_event_dataset_subject_sequence",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        default=uuid4,
        server_default=text("gen_random_uuid()"),
        primary_key=True,
    )
    dataset_version_id: Mapped[UUID] = mapped_column(index=True)
    source_record_number: Mapped[int] = mapped_column(Integer)
    unique_subject_id: Mapped[str] = mapped_column(String)
    event_sequence: Mapped[int] = mapped_column(Integer)
    reported_term: Mapped[str] = mapped_column(String)
    preferred_term: Mapped[str] = mapped_column(String)
    severity: Mapped[AdverseEventSeverity] = mapped_column(
        Enum(
            AdverseEventSeverity,
            name="adverse_event_severity",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        )
    )
    serious_flag: Mapped[str] = mapped_column(String(1))
    start_date_text: Mapped[str] = mapped_column(String)
    end_date_text: Mapped[str | None] = mapped_column(String, nullable=True)


class LBResult(Base):
    """One laboratory result linked to a DM subject in the same dataset version."""

    __tablename__ = "lb_result"
    __table_args__ = (
        CheckConstraint("source_record_number > 0", name="positive_source_record_number"),
        CheckConstraint("result_sequence > 0", name="positive_result_sequence"),
        CheckConstraint("btrim(unique_subject_id) <> ''", name="nonempty_unique_subject_id"),
        CheckConstraint("btrim(test_code) <> ''", name="nonempty_test_code"),
        CheckConstraint("btrim(observed_at_text) <> ''", name="nonempty_observed_at_text"),
        CheckConstraint("baseline_flag = 'Y'", name="baseline_flag_value"),
        ForeignKeyConstraint(
            ["dataset_version_id", "unique_subject_id"],
            ["dm_subject.dataset_version_id", "dm_subject.unique_subject_id"],
            name="fk_lb_result_dataset_subject_dm_subject",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "dataset_version_id",
            "source_record_number",
            name="uq_lb_result_dataset_record_number",
        ),
        UniqueConstraint(
            "dataset_version_id",
            "unique_subject_id",
            "result_sequence",
            name="uq_lb_result_dataset_subject_sequence",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        default=uuid4,
        server_default=text("gen_random_uuid()"),
        primary_key=True,
    )
    dataset_version_id: Mapped[UUID] = mapped_column(index=True)
    source_record_number: Mapped[int] = mapped_column(Integer)
    unique_subject_id: Mapped[str] = mapped_column(String)
    result_sequence: Mapped[int] = mapped_column(Integer)
    test_code: Mapped[str] = mapped_column(String)
    test_name: Mapped[str] = mapped_column(String)
    standard_result: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    standard_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    lower_reference_limit: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    upper_reference_limit: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    range_indicator: Mapped[NormalRangeIndicator | None] = mapped_column(
        Enum(
            NormalRangeIndicator,
            name="lb_normal_range_indicator",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        nullable=True,
    )
    baseline_flag: Mapped[str | None] = mapped_column(String(1), nullable=True)
    observed_at_text: Mapped[str] = mapped_column(String)
