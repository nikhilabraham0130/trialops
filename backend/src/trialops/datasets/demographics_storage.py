"""Transactional storage for normalized demographics subjects."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trialops.datasets.demographics import DemographicsSubject
from trialops.datasets.manifest import ArtifactKind
from trialops.datasets.models import DatasetVersion, DMSubject, SourceArtifactRecord
from trialops.studies.models import Study


class DemographicsStorageErrorCode(StrEnum):
    """Stable reasons that normalized DM subjects cannot be stored."""

    EMPTY_SUBJECT_SET = "EMPTY_SUBJECT_SET"
    DUPLICATE_SUBJECT = "DUPLICATE_SUBJECT"
    DUPLICATE_SOURCE_RECORD = "DUPLICATE_SOURCE_RECORD"
    DATASET_VERSION_NOT_FOUND = "DATASET_VERSION_NOT_FOUND"
    STUDY_MISMATCH = "STUDY_MISMATCH"
    DM_ARTIFACT_MISSING = "DM_ARTIFACT_MISSING"
    SUBJECTS_ALREADY_STORED = "SUBJECTS_ALREADY_STORED"
    DATABASE_CONFLICT = "DATABASE_CONFLICT"


class DemographicsStorageError(ValueError):
    """Raised when a normalized DM batch cannot be stored safely."""

    def __init__(self, code: DemographicsStorageErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class DemographicsStorageResult:
    """Identity and size of one successfully committed DM batch."""

    dataset_version_id: UUID
    subject_ids: tuple[UUID, ...]

    @property
    def subject_count(self) -> int:
        """Return the number of subjects committed by the transaction."""
        return len(self.subject_ids)


async def store_demographics_subjects(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    dataset_version_id: UUID,
    subjects: Sequence[DemographicsSubject],
) -> DemographicsStorageResult:
    """Store one complete normalized DM batch in a single transaction."""
    subject_batch = tuple(subjects)
    _validate_batch_identity(subject_batch)

    try:
        async with session_factory.begin() as session:
            study_oid = await session.scalar(
                select(Study.study_oid)
                .join(DatasetVersion, DatasetVersion.study_id == Study.id)
                .where(DatasetVersion.id == dataset_version_id)
            )
            if study_oid is None:
                raise DemographicsStorageError(
                    DemographicsStorageErrorCode.DATASET_VERSION_NOT_FOUND,
                    "The selected dataset version does not exist.",
                )

            if any(subject.study_id != study_oid for subject in subject_batch):
                raise DemographicsStorageError(
                    DemographicsStorageErrorCode.STUDY_MISMATCH,
                    "DM subjects do not belong to the selected dataset version's study.",
                )

            dm_artifact_id = await session.scalar(
                select(SourceArtifactRecord.id).where(
                    SourceArtifactRecord.dataset_version_id == dataset_version_id,
                    SourceArtifactRecord.kind == ArtifactKind.DATASET_JSON,
                    SourceArtifactRecord.domain == "DM",
                )
            )
            if dm_artifact_id is None:
                raise DemographicsStorageError(
                    DemographicsStorageErrorCode.DM_ARTIFACT_MISSING,
                    "The selected dataset version has no verified DM source artifact.",
                )

            existing_subject_id = await session.scalar(
                select(DMSubject.id)
                .where(DMSubject.dataset_version_id == dataset_version_id)
                .limit(1)
            )
            if existing_subject_id is not None:
                raise DemographicsStorageError(
                    DemographicsStorageErrorCode.SUBJECTS_ALREADY_STORED,
                    "DM subjects have already been stored for this dataset version.",
                )

            records = tuple(
                DMSubject(
                    id=uuid4(),
                    dataset_version_id=dataset_version_id,
                    source_record_number=subject.source_record_number,
                    unique_subject_id=subject.unique_subject_id,
                    subject_id=subject.subject_id,
                    age=subject.age,
                    age_unit=subject.age_unit,
                    sex=subject.sex,
                    race=subject.race,
                    planned_arm=subject.planned_arm,
                    actual_arm=subject.actual_arm,
                )
                for subject in subject_batch
            )
            session.add_all(records)
            result = DemographicsStorageResult(
                dataset_version_id=dataset_version_id,
                subject_ids=tuple(record.id for record in records),
            )
    except IntegrityError as exc:
        raise DemographicsStorageError(
            DemographicsStorageErrorCode.DATABASE_CONFLICT,
            "The DM dataset changed during storage; no subject records were saved.",
        ) from exc

    return result


def _validate_batch_identity(subjects: tuple[DemographicsSubject, ...]) -> None:
    """Reject incomplete or internally ambiguous subject batches."""
    if not subjects:
        raise DemographicsStorageError(
            DemographicsStorageErrorCode.EMPTY_SUBJECT_SET,
            "At least one normalized DM subject is required.",
        )

    unique_subject_ids = [subject.unique_subject_id for subject in subjects]
    if len(unique_subject_ids) != len(set(unique_subject_ids)):
        raise DemographicsStorageError(
            DemographicsStorageErrorCode.DUPLICATE_SUBJECT,
            "The normalized DM batch contains duplicate unique subject identifiers.",
        )

    source_record_numbers = [subject.source_record_number for subject in subjects]
    if len(source_record_numbers) != len(set(source_record_numbers)):
        raise DemographicsStorageError(
            DemographicsStorageErrorCode.DUPLICATE_SOURCE_RECORD,
            "The normalized DM batch contains duplicate source record numbers.",
        )
