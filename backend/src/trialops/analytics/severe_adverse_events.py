"""Deterministic subject incidence of recorded severe adverse events by actual arm."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.datasets.adverse_events import AdverseEventSeverity
from trialops.datasets.models import AEEvent, DatasetVersion, DMSubject
from trialops.validation.alt import DatasetVersionNotFoundError

METHOD_VERSION = "severe-ae-incidence/1.0"
PERCENT_PRECISION = Decimal("0.01")


class SevereAeSubject(Protocol):
    """Demographics fields needed for the population denominator."""

    @property
    def unique_subject_id(self) -> str: ...

    @property
    def actual_arm(self) -> str: ...


class SevereAeEvent(Protocol):
    """Adverse-event fields needed for classification and source evidence."""

    @property
    def source_record_number(self) -> int: ...

    @property
    def unique_subject_id(self) -> str: ...

    @property
    def severity(self) -> AdverseEventSeverity: ...

    @property
    def preferred_term(self) -> str: ...


@dataclass(frozen=True, slots=True)
class SevereAeArmResult:
    """One treatment arm's subject denominator and distinct-subject numerator."""

    arm: str
    subjects_in_arm: int
    subjects_with_severe_ae: int
    severe_ae_event_count: int
    incidence_percent: Decimal


@dataclass(frozen=True, slots=True)
class SevereAeEvidence:
    """One source AE row that contributed to an arm's severe-event count."""

    source_record_number: int
    unique_subject_id: str
    arm: str
    preferred_term: str


@dataclass(frozen=True, slots=True)
class SevereAeIncidenceResult:
    """Structured result independent of HTTP, AI wording, or persistence."""

    method_version: str
    excluded_screen_failure_subjects: int
    arms: tuple[SevereAeArmResult, ...]
    evidence: tuple[SevereAeEvidence, ...]


def calculate_severe_ae_incidence(
    subjects: Iterable[SevereAeSubject],
    events: Iterable[SevereAeEvent],
) -> SevereAeIncidenceResult:
    """Count each subject once per actual arm, even with multiple severe events."""
    arm_by_subject: dict[str, str] = {}
    denominators: dict[str, int] = {}
    excluded_screen_failure_subjects = 0
    for subject in subjects:
        if subject.unique_subject_id in arm_by_subject:
            raise ValueError("DM contains a duplicate subject identifier.")
        if not subject.actual_arm.strip():
            raise ValueError("DM contains a subject without an actual treatment arm.")
        arm_by_subject[subject.unique_subject_id] = subject.actual_arm
        if subject.actual_arm.strip().casefold() == "screen failure":
            excluded_screen_failure_subjects += 1
            continue
        denominators[subject.actual_arm] = denominators.get(subject.actual_arm, 0) + 1

    severe_subjects: dict[str, set[str]] = {arm: set() for arm in denominators}
    event_counts: dict[str, int] = {arm: 0 for arm in denominators}
    evidence: list[SevereAeEvidence] = []
    for event in events:
        try:
            arm = arm_by_subject[event.unique_subject_id]
        except KeyError as exc:
            raise ValueError(
                "AE references a subject absent from the selected DM population."
            ) from exc
        if arm.strip().casefold() == "screen failure":
            continue
        if event.severity is not AdverseEventSeverity.SEVERE:
            continue
        severe_subjects[arm].add(event.unique_subject_id)
        event_counts[arm] += 1
        evidence.append(
            SevereAeEvidence(
                source_record_number=event.source_record_number,
                unique_subject_id=event.unique_subject_id,
                arm=arm,
                preferred_term=event.preferred_term,
            )
        )

    arms = tuple(
        SevereAeArmResult(
            arm=arm,
            subjects_in_arm=denominator,
            subjects_with_severe_ae=len(severe_subjects[arm]),
            severe_ae_event_count=event_counts[arm],
            incidence_percent=(
                Decimal(100) * Decimal(len(severe_subjects[arm])) / Decimal(denominator)
            ).quantize(PERCENT_PRECISION, rounding=ROUND_HALF_UP),
        )
        for arm, denominator in sorted(denominators.items())
    )
    return SevereAeIncidenceResult(
        method_version=METHOD_VERSION,
        excluded_screen_failure_subjects=excluded_screen_failure_subjects,
        arms=arms,
        evidence=tuple(sorted(evidence, key=lambda item: item.source_record_number)),
    )


async def calculate_stored_severe_ae_incidence(
    session: AsyncSession, dataset_version_id: UUID
) -> SevereAeIncidenceResult:
    """Read DM and AE from one immutable version, never mixing data cuts."""
    version_id = await session.scalar(
        select(DatasetVersion.id).where(DatasetVersion.id == dataset_version_id)
    )
    if version_id is None:
        raise DatasetVersionNotFoundError("The selected dataset version does not exist.")

    subjects = (
        await session.scalars(
            select(DMSubject)
            .where(DMSubject.dataset_version_id == dataset_version_id)
            .order_by(DMSubject.source_record_number)
        )
    ).all()
    events = (
        await session.scalars(
            select(AEEvent)
            .where(AEEvent.dataset_version_id == dataset_version_id)
            .order_by(AEEvent.source_record_number)
        )
    ).all()
    return calculate_severe_ae_incidence(subjects, events)
