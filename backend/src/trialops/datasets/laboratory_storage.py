"""Transactional storage for normalized laboratory results."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trialops.datasets.laboratory_results import LaboratoryResult
from trialops.datasets.manifest import ArtifactKind
from trialops.datasets.models import DatasetVersion, DMSubject, LBResult, SourceArtifactRecord
from trialops.studies.models import Study

BATCH_SIZE = 1000


class LaboratoryStorageErrorCode(StrEnum):
    """Stable reasons an LB batch cannot be stored."""

    EMPTY_RESULT_SET = "EMPTY_RESULT_SET"
    DUPLICATE_RESULT = "DUPLICATE_RESULT"
    DUPLICATE_SOURCE_RECORD = "DUPLICATE_SOURCE_RECORD"
    DATASET_VERSION_NOT_FOUND = "DATASET_VERSION_NOT_FOUND"
    STUDY_MISMATCH = "STUDY_MISMATCH"
    LB_ARTIFACT_MISSING = "LB_ARTIFACT_MISSING"
    RESULTS_ALREADY_STORED = "RESULTS_ALREADY_STORED"
    SUBJECT_NOT_IN_VERSION = "SUBJECT_NOT_IN_VERSION"
    DATABASE_CONFLICT = "DATABASE_CONFLICT"


class LaboratoryStorageError(ValueError):
    """Raised when normalized LB rows cannot be committed safely."""

    def __init__(self, code: LaboratoryStorageErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class LaboratoryStorageResult:
    """Identity and size of one successfully committed LB batch."""

    dataset_version_id: UUID
    result_count: int


async def store_laboratory_results(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    dataset_version_id: UUID,
    results: Sequence[LaboratoryResult],
) -> LaboratoryStorageResult:
    """Store an LB batch atomically, linked to DM subjects in the same version."""
    result_batch = tuple(results)
    _validate_batch_identity(result_batch)

    try:
        async with session_factory.begin() as session:
            study_oid = await session.scalar(
                select(Study.study_oid)
                .join(DatasetVersion, DatasetVersion.study_id == Study.id)
                .where(DatasetVersion.id == dataset_version_id)
            )
            if study_oid is None:
                raise LaboratoryStorageError(
                    LaboratoryStorageErrorCode.DATASET_VERSION_NOT_FOUND,
                    "The selected dataset version does not exist.",
                )

            if any(result.study_id != study_oid for result in result_batch):
                raise LaboratoryStorageError(
                    LaboratoryStorageErrorCode.STUDY_MISMATCH,
                    "LB results do not belong to the selected dataset version's study.",
                )

            lb_artifact_id = await session.scalar(
                select(SourceArtifactRecord.id).where(
                    SourceArtifactRecord.dataset_version_id == dataset_version_id,
                    SourceArtifactRecord.kind == ArtifactKind.DATASET_JSON,
                    SourceArtifactRecord.domain == "LB",
                )
            )
            if lb_artifact_id is None:
                raise LaboratoryStorageError(
                    LaboratoryStorageErrorCode.LB_ARTIFACT_MISSING,
                    "The selected dataset version has no registered LB source artifact.",
                )

            existing_result_id = await session.scalar(
                select(LBResult.id)
                .where(LBResult.dataset_version_id == dataset_version_id)
                .limit(1)
            )
            if existing_result_id is not None:
                raise LaboratoryStorageError(
                    LaboratoryStorageErrorCode.RESULTS_ALREADY_STORED,
                    "LB results have already been stored for this dataset version.",
                )

            known_subject_ids = set(
                (
                    await session.scalars(
                        select(DMSubject.unique_subject_id).where(
                            DMSubject.dataset_version_id == dataset_version_id
                        )
                    )
                ).all()
            )
            result_subject_ids = {result.unique_subject_id for result in result_batch}
            if not result_subject_ids <= known_subject_ids:
                raise LaboratoryStorageError(
                    LaboratoryStorageErrorCode.SUBJECT_NOT_IN_VERSION,
                    "At least one LB subject is missing from this dataset version's DM records.",
                )

            for offset in range(0, len(result_batch), BATCH_SIZE):
                records = [
                    {
                        "id": uuid4(),
                        "dataset_version_id": dataset_version_id,
                        "source_record_number": result.source_record_number,
                        "unique_subject_id": result.unique_subject_id,
                        "result_sequence": result.result_sequence,
                        "test_code": result.test_code,
                        "test_name": result.test_name,
                        "standard_result": result.standard_result,
                        "standard_unit": result.standard_unit,
                        "lower_reference_limit": result.lower_reference_limit,
                        "upper_reference_limit": result.upper_reference_limit,
                        "range_indicator": result.range_indicator,
                        "baseline_flag": result.baseline_flag,
                        "observed_at_text": result.observed_at_text,
                    }
                    for result in result_batch[offset : offset + BATCH_SIZE]
                ]
                await session.execute(insert(LBResult), records)
    except IntegrityError as exc:
        raise LaboratoryStorageError(
            LaboratoryStorageErrorCode.DATABASE_CONFLICT,
            "The LB dataset changed during storage; no result records were saved.",
        ) from exc

    return LaboratoryStorageResult(dataset_version_id, len(result_batch))


def _validate_batch_identity(results: tuple[LaboratoryResult, ...]) -> None:
    """Reject incomplete or internally ambiguous LB batches before database work."""
    if not results:
        raise LaboratoryStorageError(
            LaboratoryStorageErrorCode.EMPTY_RESULT_SET,
            "At least one normalized LB result is required.",
        )

    result_keys = [(result.unique_subject_id, result.result_sequence) for result in results]
    if len(result_keys) != len(set(result_keys)):
        raise LaboratoryStorageError(
            LaboratoryStorageErrorCode.DUPLICATE_RESULT,
            "The normalized LB batch contains duplicate subject and sequence pairs.",
        )

    source_record_numbers = [result.source_record_number for result in results]
    if len(source_record_numbers) != len(set(source_record_numbers)):
        raise LaboratoryStorageError(
            LaboratoryStorageErrorCode.DUPLICATE_SOURCE_RECORD,
            "The normalized LB batch contains duplicate source record numbers.",
        )
