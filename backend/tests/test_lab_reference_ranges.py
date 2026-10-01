"""Tests for the per-test, row-specific laboratory reference range check."""

from dataclasses import dataclass
from decimal import Decimal

import pytest

from trialops.analytics.lab_reference_ranges import (
    LabTestNotFoundError,
    RangeDirection,
    calculate_lab_reference_range,
)


@dataclass(frozen=True)
class Row:
    source_record_number: int
    unique_subject_id: str
    test_code: str
    standard_result: Decimal | None
    lower_reference_limit: Decimal | None
    upper_reference_limit: Decimal | None
    standard_unit: str | None = "U/L"
    baseline_flag: str | None = None


def row(
    number: int,
    subject: str,
    value: str | None,
    lower: str | None = "0",
    upper: str | None = "40",
    *,
    test_code: str = "AST",
    baseline_flag: str | None = None,
) -> Row:
    return Row(
        number,
        subject,
        test_code,
        Decimal(value) if value is not None else None,
        Decimal(lower) if lower is not None else None,
        Decimal(upper) if upper is not None else None,
        baseline_flag=baseline_flag,
    )


def test_classifies_strictly_outside_each_rows_own_limits() -> None:
    result = calculate_lab_reference_range(
        [
            row(4, "S2", "-1"),
            row(3, "S1", "41", baseline_flag="Y"),
            row(1, "S1", "50", upper="60"),
            row(2, "S1", "40"),
            row(5, "S2", "0"),
            row(6, "S3", "99", test_code="ALT"),
        ],
        "AST",
    )
    assert result.total_rows == result.eligible_rows == 5
    assert result.excluded_rows == 0
    assert result.out_of_range_rows == 2
    assert result.below_lower_rows == result.above_upper_rows == 1
    assert result.subjects_with_out_of_range == 2
    assert [event.source_record_number for event in result.evidence] == [3, 4]
    assert result.evidence[0].baseline_flag == "Y"
    assert result.evidence[1].direction is RangeDirection.BELOW_LOWER


def test_excludes_missing_nonfinite_or_inverted_limits_without_calling_rows_normal() -> None:
    result = calculate_lab_reference_range(
        [
            row(1, "S1", None),
            row(2, "S1", "40", lower=None),
            row(3, "S1", "40", upper=None),
            row(4, "S1", "40", lower="50", upper="40"),
            row(5, "S1", "40", lower="40", upper="40"),
            row(6, "S1", "40", lower="-Infinity"),
            row(7, "S1", "40", lower="0", upper="50"),
        ],
        "AST",
    )
    assert result.total_rows == 7
    assert result.eligible_rows == 1
    assert result.excluded_rows == 6
    assert result.out_of_range_rows == 0


def test_rejects_unknown_test_code() -> None:
    with pytest.raises(LabTestNotFoundError):
        calculate_lab_reference_range([row(1, "S1", "40")], "BILI")


def test_evidence_display_is_bounded_without_losing_total_counts() -> None:
    result = calculate_lab_reference_range(
        [row(number, "S1", "41") for number in range(1, 206)], "AST"
    )
    assert result.out_of_range_rows == 205
    assert result.subjects_with_out_of_range == 1
    assert len(result.evidence) == 200
    assert result.evidence_truncated
