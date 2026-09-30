"""Descriptive source-linked safety profile for one subject and dataset version."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.datasets.adverse_events import AdverseEventSeverity
from trialops.datasets.laboratory_results import NormalRangeIndicator
from trialops.datasets.models import AEEvent, DatasetVersion, DMSubject, LBResult
from trialops.validation.alt import DatasetVersionNotFoundError

METHOD_VERSION = "subject-safety-summary/1.0"


class SubjectNotFoundError(ValueError):
    """The requested subject is absent from the selected immutable version."""


class SubjectRecord(Protocol):
    unique_subject_id: str
    actual_arm: str
    age: int
    age_unit: str
    sex: str


class EventRecord(Protocol):
    source_record_number: int
    unique_subject_id: str
    preferred_term: str
    severity: AdverseEventSeverity
    serious_flag: str
    start_date_text: str


class LabRecord(Protocol):
    source_record_number: int
    unique_subject_id: str
    test_code: str
    standard_result: Decimal | None
    standard_unit: str | None
    lower_reference_limit: Decimal | None
    upper_reference_limit: Decimal | None
    range_indicator: NormalRangeIndicator | None
    baseline_flag: str | None
    observed_at_text: str


@dataclass(frozen=True, slots=True)
class SafetyEvent:
    source_record_number: int
    preferred_term: str
    severity: AdverseEventSeverity
    serious_flag: str
    start_date_text: str


@dataclass(frozen=True, slots=True)
class FlaggedLab:
    source_record_number: int
    test_code: str
    standard_result: Decimal | None
    standard_unit: str | None
    lower_reference_limit: Decimal | None
    upper_reference_limit: Decimal | None
    range_indicator: NormalRangeIndicator
    baseline_flag: str | None
    observed_at_text: str


@dataclass(frozen=True, slots=True)
class SubjectSafetySummary:
    method_version: str
    unique_subject_id: str
    actual_arm: str
    age: int
    age_unit: str
    sex: str
    ae_event_count: int
    severe_ae_event_count: int
    serious_ae_event_count: int
    lab_result_count: int
    flagged_lab_count: int
    events: tuple[SafetyEvent, ...]
    flagged_labs: tuple[FlaggedLab, ...]


def build_subject_safety_summary(
    subject: SubjectRecord,
    events: Iterable[EventRecord],
    labs: Iterable[LabRecord],
) -> SubjectSafetySummary:
    """Count source records without conflating severity, seriousness, or lab flags."""
    event_rows = tuple(events)
    lab_rows = tuple(labs)
    if any(event.unique_subject_id != subject.unique_subject_id for event in event_rows):
        raise ValueError("AE rows include a different subject.")
    if any(lab.unique_subject_id != subject.unique_subject_id for lab in lab_rows):
        raise ValueError("LB rows include a different subject.")

    flagged_labs = tuple(
        FlaggedLab(
            source_record_number=lab.source_record_number,
            test_code=lab.test_code,
            standard_result=lab.standard_result,
            standard_unit=lab.standard_unit,
            lower_reference_limit=lab.lower_reference_limit,
            upper_reference_limit=lab.upper_reference_limit,
            range_indicator=lab.range_indicator,
            baseline_flag=lab.baseline_flag,
            observed_at_text=lab.observed_at_text,
        )
        for lab in sorted(lab_rows, key=lambda row: row.source_record_number)
        if lab.range_indicator
        in {
            NormalRangeIndicator.LOW,
            NormalRangeIndicator.HIGH,
            NormalRangeIndicator.ABNORMAL,
        }
        and lab.range_indicator is not None
    )
    return SubjectSafetySummary(
        method_version=METHOD_VERSION,
        unique_subject_id=subject.unique_subject_id,
        actual_arm=subject.actual_arm,
        age=subject.age,
        age_unit=subject.age_unit,
        sex=subject.sex,
        ae_event_count=len(event_rows),
        severe_ae_event_count=sum(
            event.severity is AdverseEventSeverity.SEVERE for event in event_rows
        ),
        serious_ae_event_count=sum(event.serious_flag == "Y" for event in event_rows),
        lab_result_count=len(lab_rows),
        flagged_lab_count=len(flagged_labs),
        events=tuple(
            SafetyEvent(
                source_record_number=event.source_record_number,
                preferred_term=event.preferred_term,
                severity=event.severity,
                serious_flag=event.serious_flag,
                start_date_text=event.start_date_text,
            )
            for event in sorted(event_rows, key=lambda row: row.source_record_number)
        ),
        flagged_labs=flagged_labs,
    )


async def get_stored_subject_safety_summary(
    session: AsyncSession, dataset_version_id: UUID, unique_subject_id: str
) -> SubjectSafetySummary:
    """Read a subject, events, and labs only from the requested dataset version."""
    version_id = await session.scalar(
        select(DatasetVersion.id).where(DatasetVersion.id == dataset_version_id)
    )
    if version_id is None:
        raise DatasetVersionNotFoundError("The selected dataset version does not exist.")

    subject = await session.scalar(
        select(DMSubject).where(
            DMSubject.dataset_version_id == dataset_version_id,
            DMSubject.unique_subject_id == unique_subject_id,
        )
    )
    if subject is None:
        raise SubjectNotFoundError("The subject is not in the selected dataset version.")

    events = (
        await session.scalars(
            select(AEEvent)
            .where(
                AEEvent.dataset_version_id == dataset_version_id,
                AEEvent.unique_subject_id == unique_subject_id,
            )
            .order_by(AEEvent.source_record_number)
        )
    ).all()
    labs = (
        await session.scalars(
            select(LBResult)
            .where(
                LBResult.dataset_version_id == dataset_version_id,
                LBResult.unique_subject_id == unique_subject_id,
            )
            .order_by(LBResult.source_record_number)
        )
    ).all()
    return build_subject_safety_summary(subject, events, labs)
