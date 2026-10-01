"""Tests for distinct-subject serious-AE incidence, separate from severity."""

from dataclasses import dataclass
from decimal import Decimal

import pytest

from trialops.analytics.serious_adverse_events import (
    METHOD_VERSION,
    calculate_serious_ae_incidence,
)


@dataclass(frozen=True)
class Subject:
    unique_subject_id: str
    actual_arm: str


@dataclass(frozen=True)
class Event:
    source_record_number: int
    unique_subject_id: str
    serious_flag: str
    preferred_term: str = "Headache"


def test_counts_subjects_once_but_each_serious_event_separately() -> None:
    result = calculate_serious_ae_incidence(
        [
            Subject("P1", "Placebo"),
            Subject("P2", "Placebo"),
            Subject("T1", "Treatment"),
            Subject("T2", "Treatment"),
            Subject("S1", "Screen Failure"),
        ],
        [
            Event(3, "T1", "Y"),
            Event(1, "P1", "Y"),
            Event(2, "P1", "Y"),
            Event(4, "T2", "N"),
            Event(5, "S1", "Y"),
        ],
    )
    assert result.method_version == METHOD_VERSION
    assert [
        (
            arm.arm,
            arm.subjects_in_arm,
            arm.subjects_with_serious_ae,
            arm.serious_ae_event_count,
            arm.incidence_percent,
        )
        for arm in result.arms
    ] == [
        ("Placebo", 2, 1, 2, Decimal("50.00")),
        ("Treatment", 2, 1, 1, Decimal("50.00")),
    ]
    assert [row.source_record_number for row in result.evidence] == [1, 2, 3]
    assert result.excluded_screen_failure_subjects == 1


def test_zero_event_arm_and_percentage_rounding() -> None:
    result = calculate_serious_ae_incidence(
        [Subject("A", "A"), Subject("B", "A"), Subject("C", "A"), Subject("D", "B")],
        [Event(1, "A", "Y")],
    )
    assert result.arms[0].incidence_percent == Decimal("33.33")
    assert result.arms[1].incidence_percent == Decimal("0.00")


@pytest.mark.parametrize(
    ("subjects", "events", "message"),
    [
        ([Subject("A", "Placebo"), Subject("A", "Placebo")], [], "duplicate"),
        ([Subject("A", " ")], [], "without an actual treatment arm"),
        (
            [Subject("A", "Placebo")],
            [Event(1, "missing", "N")],
            "absent from the selected DM population",
        ),
    ],
)
def test_rejects_inconsistent_source_inputs(
    subjects: list[Subject], events: list[Event], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_serious_ae_incidence(subjects, events)
