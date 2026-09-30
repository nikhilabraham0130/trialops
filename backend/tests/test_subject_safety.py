"""Subject-level safety aggregation keeps AE, LB, and DM semantics separate."""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.analytics.subject_safety import (
    SubjectNotFoundError,
    build_subject_safety_summary,
    get_stored_subject_safety_summary,
)
from trialops.datasets.adverse_events import AdverseEventSeverity
from trialops.datasets.laboratory_results import NormalRangeIndicator
from trialops.validation.alt import DatasetVersionNotFoundError


@dataclass
class Subject:
    unique_subject_id: str = "S1"
    actual_arm: str = "Placebo"
    age: int = 55
    age_unit: str = "YEARS"
    sex: str = "F"


@dataclass
class Event:
    source_record_number: int
    severity: AdverseEventSeverity
    serious_flag: str
    unique_subject_id: str = "S1"
    preferred_term: str = "Headache"
    start_date_text: str = "2020-01-01"


@dataclass
class Lab:
    source_record_number: int
    range_indicator: NormalRangeIndicator | None
    unique_subject_id: str = "S1"
    test_code: str = "ALT"
    standard_result: Decimal | None = Decimal("50")
    standard_unit: str | None = "U/L"
    lower_reference_limit: Decimal | None = Decimal("10")
    upper_reference_limit: Decimal | None = Decimal("40")
    baseline_flag: str | None = None
    observed_at_text: str = "2020-01-02"


def test_summary_distinguishes_severity_seriousness_and_source_lab_flags() -> None:
    result = build_subject_safety_summary(
        Subject(),
        [
            Event(3, AdverseEventSeverity.SEVERE, "N"),
            Event(1, AdverseEventSeverity.MILD, "Y"),
        ],
        [Lab(8, NormalRangeIndicator.NORMAL), Lab(5, NormalRangeIndicator.HIGH)],
    )
    assert result.ae_event_count == 2
    assert result.severe_ae_event_count == 1
    assert result.serious_ae_event_count == 1
    assert result.lab_result_count == 2
    assert result.flagged_lab_count == 1
    assert [row.source_record_number for row in result.events] == [1, 3]
    assert result.flagged_labs[0].source_record_number == 5


def test_summary_can_return_zero_event_and_zero_flagged_lab_counts() -> None:
    result = build_subject_safety_summary(Subject(), [], [Lab(1, None)])
    assert result.ae_event_count == 0
    assert result.flagged_lab_count == 0
    assert result.lab_result_count == 1


@pytest.mark.parametrize("domain", ["AE", "LB"])
def test_summary_rejects_rows_for_another_subject(domain: str) -> None:
    events = [Event(1, AdverseEventSeverity.SEVERE, "N", "OTHER")] if domain == "AE" else []
    labs = [Lab(1, NormalRangeIndicator.HIGH, "OTHER")] if domain == "LB" else []
    with pytest.raises(ValueError, match=domain):
        build_subject_safety_summary(Subject(), events, labs)


class Rows:
    def __init__(self, values: list[Event] | list[Lab]) -> None:
        self.values = values

    def all(self) -> list[Event] | list[Lab]:
        return self.values


class Session:
    def __init__(self, *, version_exists: bool = True, subject_exists: bool = True) -> None:
        self.version_exists = version_exists
        self.subject_exists = subject_exists
        self.scalar_calls = 0
        self.scalars_calls = 0

    async def scalar(self, _query: object) -> object | None:
        self.scalar_calls += 1
        if self.scalar_calls == 1:
            return uuid4() if self.version_exists else None
        return Subject() if self.subject_exists else None

    async def scalars(self, _query: object) -> Rows:
        self.scalars_calls += 1
        if self.scalars_calls == 1:
            return Rows([Event(1, AdverseEventSeverity.SEVERE, "N")])
        return Rows([Lab(2, NormalRangeIndicator.HIGH)])


def test_stored_summary_reads_three_domains_for_selected_subject() -> None:
    session = Session()
    result = asyncio.run(
        get_stored_subject_safety_summary(cast(AsyncSession, session), uuid4(), "S1")
    )
    assert result.severe_ae_event_count == 1
    assert result.flagged_lab_count == 1
    assert session.scalar_calls == 2
    assert session.scalars_calls == 2


def test_stored_summary_rejects_unknown_version_before_subject_lookup() -> None:
    session = Session(version_exists=False)
    with pytest.raises(DatasetVersionNotFoundError):
        asyncio.run(get_stored_subject_safety_summary(cast(AsyncSession, session), uuid4(), "S1"))
    assert session.scalar_calls == 1


def test_stored_summary_rejects_unknown_subject_before_event_lookup() -> None:
    session = Session(subject_exists=False)
    with pytest.raises(SubjectNotFoundError):
        asyncio.run(get_stored_subject_safety_summary(cast(AsyncSession, session), uuid4(), "S1"))
    assert session.scalars_calls == 0
