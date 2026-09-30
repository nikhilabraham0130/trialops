"""Tests for descriptive, distinct-subject severe-AE incidence."""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.analytics.severe_adverse_events import (
    METHOD_VERSION,
    calculate_severe_ae_incidence,
    calculate_stored_severe_ae_incidence,
)
from trialops.datasets.adverse_events import AdverseEventSeverity
from trialops.validation.alt import DatasetVersionNotFoundError


@dataclass(frozen=True)
class Subject:
    unique_subject_id: str
    actual_arm: str


@dataclass(frozen=True)
class Event:
    source_record_number: int
    unique_subject_id: str
    severity: AdverseEventSeverity
    preferred_term: str = "Headache"


def test_counts_distinct_subjects_and_events_separately_by_actual_arm() -> None:
    result = calculate_severe_ae_incidence(
        [
            Subject("P1", "Placebo"),
            Subject("P2", "Placebo"),
            Subject("T1", "Treatment"),
            Subject("T2", "Treatment"),
            Subject("S1", "Screen Failure"),
        ],
        [
            Event(12, "T1", AdverseEventSeverity.SEVERE),
            Event(10, "P1", AdverseEventSeverity.SEVERE),
            Event(13, "T1", AdverseEventSeverity.SEVERE),
            Event(11, "P2", AdverseEventSeverity.MILD),
            Event(14, "S1", AdverseEventSeverity.SEVERE),
        ],
    )

    assert result.method_version == METHOD_VERSION
    assert [
        (
            arm.arm,
            arm.subjects_in_arm,
            arm.subjects_with_severe_ae,
            arm.severe_ae_event_count,
            arm.incidence_percent,
        )
        for arm in result.arms
    ] == [
        ("Placebo", 2, 1, 1, Decimal("50.00")),
        ("Treatment", 2, 1, 2, Decimal("50.00")),
    ]
    assert [item.source_record_number for item in result.evidence] == [10, 12, 13]
    assert result.evidence[1].unique_subject_id == "T1"
    assert result.excluded_screen_failure_subjects == 1


def test_zero_event_arm_and_non_terminating_percentage_rounding() -> None:
    result = calculate_severe_ae_incidence(
        [Subject("A", "A"), Subject("B", "A"), Subject("C", "A"), Subject("D", "B")],
        [Event(1, "A", AdverseEventSeverity.SEVERE)],
    )

    assert result.arms[0].incidence_percent == Decimal("33.33")
    assert result.arms[1].incidence_percent == Decimal("0.00")
    assert result.arms[1].subjects_with_severe_ae == 0


@pytest.mark.parametrize(
    ("subjects", "events", "message"),
    [
        ([Subject("A", "Placebo"), Subject("A", "Placebo")], [], "duplicate"),
        ([Subject("A", " ")], [], "without an actual treatment arm"),
        (
            [Subject("A", "Placebo")],
            [Event(1, "missing", AdverseEventSeverity.MILD)],
            "absent from the selected DM population",
        ),
    ],
)
def test_rejects_inconsistent_source_inputs(
    subjects: list[Subject], events: list[Event], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_severe_ae_incidence(subjects, events)


class FakeScalarResult:
    def __init__(self, rows: list[Subject] | list[Event]) -> None:
        self.rows = rows

    def all(self) -> list[Subject] | list[Event]:
        return self.rows


class FakeSession:
    def __init__(self, version_exists: bool) -> None:
        self.version_exists = version_exists
        self.scalar_calls = 0
        self.scalars_calls = 0

    async def scalar(self, _query: object) -> object | None:
        self.scalar_calls += 1
        return uuid4() if self.version_exists else None

    async def scalars(self, _query: object) -> FakeScalarResult:
        self.scalars_calls += 1
        if self.scalars_calls == 1:
            return FakeScalarResult([Subject("A", "Placebo")])
        return FakeScalarResult([Event(1, "A", AdverseEventSeverity.SEVERE)])


def test_stored_calculation_reads_subjects_and_events_from_one_version() -> None:
    session = FakeSession(version_exists=True)
    result = asyncio.run(calculate_stored_severe_ae_incidence(cast(AsyncSession, session), uuid4()))

    assert result.arms[0].subjects_with_severe_ae == 1
    assert session.scalar_calls == 1
    assert session.scalars_calls == 2


def test_stored_calculation_rejects_unknown_version_before_reading_rows() -> None:
    session = FakeSession(version_exists=False)
    with pytest.raises(DatasetVersionNotFoundError):
        asyncio.run(calculate_stored_severe_ae_incidence(cast(AsyncSession, session), uuid4()))
    assert session.scalars_calls == 0
