"""Transactional storage for normalized adverse-event records."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trialops.datasets.adverse_events import AdverseEvent
from trialops.datasets.manifest import ArtifactKind
from trialops.datasets.models import AEEvent, DatasetVersion, DMSubject, SourceArtifactRecord
from trialops.studies.models import Study


class AdverseEventStorageErrorCode(StrEnum):
    """Stable reasons an AE batch cannot be stored."""

    EMPTY_EVENT_SET = "EMPTY_EVENT_SET"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    DUPLICATE_SOURCE_RECORD = "DUPLICATE_SOURCE_RECORD"
    DATASET_VERSION_NOT_FOUND = "DATASET_VERSION_NOT_FOUND"
    STUDY_MISMATCH = "STUDY_MISMATCH"
    AE_ARTIFACT_MISSING = "AE_ARTIFACT_MISSING"
    EVENTS_ALREADY_STORED = "EVENTS_ALREADY_STORED"
    SUBJECT_NOT_IN_VERSION = "SUBJECT_NOT_IN_VERSION"
    DATABASE_CONFLICT = "DATABASE_CONFLICT"


class AdverseEventStorageError(ValueError):
    """Raised when normalized AE rows cannot be committed safely."""

    def __init__(self, code: AdverseEventStorageErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AdverseEventStorageResult:
    """Identity and size of one successfully committed AE batch."""

    dataset_version_id: UUID
    event_ids: tuple[UUID, ...]

    @property
    def event_count(self) -> int:
        """Return the number of AE rows committed by the transaction."""
        return len(self.event_ids)


async def store_adverse_events(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    dataset_version_id: UUID,
    events: Sequence[AdverseEvent],
) -> AdverseEventStorageResult:
    """Store one AE batch atomically after checking its version and DM subjects."""
    event_batch = tuple(events)
    _validate_batch_identity(event_batch)

    try:
        async with session_factory.begin() as session:
            study_oid = await session.scalar(
                select(Study.study_oid)
                .join(DatasetVersion, DatasetVersion.study_id == Study.id)
                .where(DatasetVersion.id == dataset_version_id)
            )
            if study_oid is None:
                raise AdverseEventStorageError(
                    AdverseEventStorageErrorCode.DATASET_VERSION_NOT_FOUND,
                    "The selected dataset version does not exist.",
                )

            if any(event.study_id != study_oid for event in event_batch):
                raise AdverseEventStorageError(
                    AdverseEventStorageErrorCode.STUDY_MISMATCH,
                    "AE events do not belong to the selected dataset version's study.",
                )

            ae_artifact_id = await session.scalar(
                select(SourceArtifactRecord.id).where(
                    SourceArtifactRecord.dataset_version_id == dataset_version_id,
                    SourceArtifactRecord.kind == ArtifactKind.DATASET_JSON,
                    SourceArtifactRecord.domain == "AE",
                )
            )
            if ae_artifact_id is None:
                raise AdverseEventStorageError(
                    AdverseEventStorageErrorCode.AE_ARTIFACT_MISSING,
                    "The selected dataset version has no registered AE source artifact.",
                )

            existing_event_id = await session.scalar(
                select(AEEvent.id).where(AEEvent.dataset_version_id == dataset_version_id).limit(1)
            )
            if existing_event_id is not None:
                raise AdverseEventStorageError(
                    AdverseEventStorageErrorCode.EVENTS_ALREADY_STORED,
                    "AE events have already been stored for this dataset version.",
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
            event_subject_ids = {event.unique_subject_id for event in event_batch}
            if not event_subject_ids <= known_subject_ids:
                raise AdverseEventStorageError(
                    AdverseEventStorageErrorCode.SUBJECT_NOT_IN_VERSION,
                    "At least one AE subject is missing from this dataset version's DM records.",
                )

            records = tuple(
                AEEvent(
                    id=uuid4(),
                    dataset_version_id=dataset_version_id,
                    source_record_number=event.source_record_number,
                    unique_subject_id=event.unique_subject_id,
                    event_sequence=event.event_sequence,
                    reported_term=event.reported_term,
                    preferred_term=event.preferred_term,
                    severity=event.severity,
                    serious_flag=event.serious_flag,
                    start_date_text=event.start_date_text,
                    end_date_text=event.end_date_text,
                )
                for event in event_batch
            )
            session.add_all(records)
            result = AdverseEventStorageResult(
                dataset_version_id=dataset_version_id,
                event_ids=tuple(record.id for record in records),
            )
    except IntegrityError as exc:
        raise AdverseEventStorageError(
            AdverseEventStorageErrorCode.DATABASE_CONFLICT,
            "The AE dataset changed during storage; no event records were saved.",
        ) from exc

    return result


def _validate_batch_identity(events: tuple[AdverseEvent, ...]) -> None:
    """Reject incomplete or internally ambiguous AE batches before database work."""
    if not events:
        raise AdverseEventStorageError(
            AdverseEventStorageErrorCode.EMPTY_EVENT_SET,
            "At least one normalized AE event is required.",
        )

    event_keys = [(event.unique_subject_id, event.event_sequence) for event in events]
    if len(event_keys) != len(set(event_keys)):
        raise AdverseEventStorageError(
            AdverseEventStorageErrorCode.DUPLICATE_EVENT,
            "The normalized AE batch contains duplicate subject and sequence pairs.",
        )

    source_record_numbers = [event.source_record_number for event in events]
    if len(source_record_numbers) != len(set(source_record_numbers)):
        raise AdverseEventStorageError(
            AdverseEventStorageErrorCode.DUPLICATE_SOURCE_RECORD,
            "The normalized AE batch contains duplicate source record numbers.",
        )
