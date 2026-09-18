"""Tests for deterministic ALT-analysis prerequisite checks."""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.validation.alt import (
    DatasetVersionNotFoundError,
    check_alt_prerequisites,
    check_stored_alt_prerequisites,
)
from trialops.validation.findings import FindingSeverity


@dataclass(frozen=True)
class _Row:
    source_record_number: int
    test_code: str
    standard_result: Decimal | None
    upper_reference_limit: Decimal | None


def test_valid_alt_row_includes_numeric_zero_result() -> None:
    report = check_alt_prerequisites([_Row(1, "ALT", Decimal(0), Decimal(40))])

    assert report.alt_row_count == 1
    assert report.eligible_row_count == 1
    assert report.findings == ()


def test_unrelated_labs_do_not_affect_alt_report() -> None:
    report = check_alt_prerequisites(
        [_Row(1, "ALB", None, None), _Row(2, "ALT", Decimal(10), Decimal(40))]
    )

    assert report.alt_row_count == 1
    assert report.eligible_row_count == 1
    assert report.findings == ()


@pytest.mark.parametrize("upper_limit", [None, Decimal(0), Decimal(-1), Decimal("NaN")])
def test_missing_nonpositive_or_nonfinite_upper_limit_excludes_alt_row(
    upper_limit: Decimal | None,
) -> None:
    report = check_alt_prerequisites([_Row(3, "ALT", Decimal(25), upper_limit)])

    assert report.alt_row_count == 1
    assert report.eligible_row_count == 0
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.rule_code == "ALT_UPPER_LIMIT_MISSING_OR_INVALID"
    assert finding.severity is FindingSeverity.WARNING
    assert finding.domain == "LB"
    assert finding.source_record_number == 3


@pytest.mark.parametrize("value", [None, Decimal("NaN"), Decimal("Infinity")])
def test_missing_or_nonfinite_result_excludes_alt_row(value: Decimal | None) -> None:
    report = check_alt_prerequisites([_Row(4, "ALT", value, Decimal(40))])

    assert report.eligible_row_count == 0
    assert [finding.rule_code for finding in report.findings] == ["ALT_RESULT_MISSING_OR_INVALID"]


def test_both_invalid_fields_produce_both_findings_for_same_source_row() -> None:
    report = check_alt_prerequisites([_Row(5, "ALT", None, None)])

    assert report.eligible_row_count == 0
    assert [finding.source_record_number for finding in report.findings] == [5, 5]
    assert [finding.rule_code for finding in report.findings] == [
        "ALT_RESULT_MISSING_OR_INVALID",
        "ALT_UPPER_LIMIT_MISSING_OR_INVALID",
    ]


def test_no_alt_rows_blocks_alt_analysis_only() -> None:
    report = check_alt_prerequisites([_Row(1, "ALB", Decimal(4), None)])

    assert report.alt_row_count == 0
    assert report.eligible_row_count == 0
    assert len(report.findings) == 1
    assert report.findings[0].rule_code == "ALT_RESULTS_MISSING"
    assert report.findings[0].severity is FindingSeverity.BLOCKING
    assert report.findings[0].source_record_number is None


def test_many_alt_rows_report_eligible_subset_in_source_order() -> None:
    report = check_alt_prerequisites(
        [
            _Row(1, "ALT", Decimal(1), Decimal(40)),
            _Row(2, "ALT", None, Decimal(40)),
            _Row(3, "ALT", Decimal(0), Decimal(40)),
        ]
    )

    assert report.alt_row_count == 3
    assert report.eligible_row_count == 2
    assert [finding.source_record_number for finding in report.findings] == [2]


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


def test_stored_check_reads_only_selected_version_and_alt_code() -> None:
    version_id = uuid4()
    fake = _FakeSession(version_id, [_Row(1, "ALT", Decimal(25), Decimal(40))])

    report = asyncio.run(check_stored_alt_prerequisites(cast(AsyncSession, fake), version_id))

    assert report.eligible_row_count == 1
    assert len(fake.statements) == 2
    for statement in fake.statements:
        assert version_id in statement.compile().params.values()  # type: ignore[attr-defined]
    second = fake.statements[1]
    assert "ALT" in second.compile().params.values()  # type: ignore[attr-defined]
    assert "lb_result" in str(second)


def test_stored_check_rejects_unknown_version_without_querying_labs() -> None:
    fake = _FakeSession(None, [])
    with pytest.raises(DatasetVersionNotFoundError):
        asyncio.run(check_stored_alt_prerequisites(cast(AsyncSession, fake), uuid4()))
    assert len(fake.statements) == 1
