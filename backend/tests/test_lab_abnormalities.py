"""Tests for deterministic ALT threshold calculations."""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.analytics.lab_abnormalities import (
    METHOD_VERSION,
    AltAbnormalityResult,
    TimingClassification,
    calculate_alt_gt_3x_uln,
    calculate_stored_alt_gt_3x_uln,
)
from trialops.validation.alt import DatasetVersionNotFoundError


@dataclass(frozen=True)
class _Row:
    source_record_number: int
    unique_subject_id: str
    test_code: str
    standard_result: Decimal | None
    upper_reference_limit: Decimal | None
    baseline_flag: str | None


def test_result_strictly_above_three_times_uln_is_an_exceedance() -> None:
    result = calculate_alt_gt_3x_uln(
        [_Row(1, "SUBJECT-1", "ALT", Decimal("120.01"), Decimal(40), None)]
    )

    assert result.method_version == METHOD_VERSION
    assert result.threshold_multiplier == Decimal(3)
    assert result.alt_row_count == result.eligible_row_count == 1
    assert result.excluded_row_count == 0
    assert result.exceedance_count == 1
    assert result.subjects_with_exceedance == 1
    assert result.exceedances[0].threshold == Decimal(120)
    assert result.exceedances[0].timing is TimingClassification.NOT_IDENTIFIED_AS_BASELINE


@pytest.mark.parametrize("value", [Decimal(0), Decimal(119), Decimal(120)])
def test_result_at_or_below_threshold_is_not_an_exceedance(value: Decimal) -> None:
    result = calculate_alt_gt_3x_uln([_Row(1, "SUBJECT-1", "ALT", value, Decimal(40), None)])

    assert result.eligible_row_count == 1
    assert result.exceedance_count == 0
    assert result.subjects_with_exceedance == 0


def test_baseline_exceedance_is_labeled_without_being_discarded() -> None:
    result = calculate_alt_gt_3x_uln([_Row(7, "SUBJECT-1", "ALT", Decimal(150), Decimal(40), "Y")])

    evidence = result.exceedances[0]
    assert evidence.source_record_number == 7
    assert evidence.unique_subject_id == "SUBJECT-1"
    assert evidence.standard_result == Decimal(150)
    assert evidence.upper_reference_limit == Decimal(40)
    assert evidence.timing is TimingClassification.BASELINE


def test_multiple_exceeding_rows_for_one_subject_count_one_subject() -> None:
    result = calculate_alt_gt_3x_uln(
        [
            _Row(1, "SUBJECT-1", "ALT", Decimal(150), Decimal(40), None),
            _Row(2, "SUBJECT-1", "ALT", Decimal(160), Decimal(40), None),
            _Row(3, "SUBJECT-2", "ALT", Decimal(200), Decimal(40), None),
        ]
    )

    assert result.exceedance_count == 3
    assert result.subjects_with_exceedance == 2


def test_invalid_alt_row_is_excluded_with_finding() -> None:
    result = calculate_alt_gt_3x_uln([_Row(4, "SUBJECT-1", "ALT", Decimal(150), Decimal(0), None)])

    assert result.alt_row_count == 1
    assert result.eligible_row_count == 0
    assert result.excluded_row_count == 1
    assert result.exceedances == ()
    assert [finding.rule_code for finding in result.findings] == [
        "ALT_UPPER_LIMIT_MISSING_OR_INVALID"
    ]


def test_non_alt_row_is_ignored_and_absence_is_reported() -> None:
    result = calculate_alt_gt_3x_uln([_Row(1, "SUBJECT-1", "AST", Decimal(200), Decimal(40), None)])

    assert result.alt_row_count == 0
    assert result.eligible_row_count == 0
    assert result.exceedance_count == 0
    assert result.findings[0].rule_code == "ALT_RESULTS_MISSING"


class _ScalarRows:
    def __init__(self, rows: list[_Row]) -> None:
        self.rows = rows

    def all(self) -> list[_Row]:
        return self.rows


class _FakeSession:
    def __init__(self, version_id: UUID | None, rows: list[_Row]) -> None:
        self.version_id = version_id
        self.rows = rows
        self.statements: list[object] = []

    async def scalar(self, statement: object) -> UUID | None:
        self.statements.append(statement)
        return self.version_id

    async def scalars(self, statement: object) -> _ScalarRows:
        self.statements.append(statement)
        return _ScalarRows(self.rows)


def _stored(fake: _FakeSession, version_id: UUID) -> AltAbnormalityResult:
    return asyncio.run(calculate_stored_alt_gt_3x_uln(cast(AsyncSession, fake), version_id))


def test_stored_calculation_reads_alt_from_only_selected_version() -> None:
    version_id = uuid4()
    fake = _FakeSession(
        version_id,
        [_Row(1, "SUBJECT-1", "ALT", Decimal(150), Decimal(40), None)],
    )

    result = _stored(fake, version_id)

    assert result.exceedance_count == 1
    assert len(fake.statements) == 2
    for statement in fake.statements:
        assert version_id in statement.compile().params.values()  # type: ignore[attr-defined]
    assert "ALT" in fake.statements[1].compile().params.values()  # type: ignore[attr-defined]


def test_stored_calculation_rejects_unknown_version_without_querying_rows() -> None:
    fake = _FakeSession(None, [])
    with pytest.raises(DatasetVersionNotFoundError):
        _stored(fake, uuid4())
    assert len(fake.statements) == 1
