"""Descriptive classification against each LB row's supplied reference limits."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.datasets.models import DatasetVersion, LBResult
from trialops.validation.alt import DatasetVersionNotFoundError

METHOD_VERSION = "lab-reference-range/1.0"
MAX_EVIDENCE_ROWS = 200


class LabTestNotFoundError(ValueError):
    """The selected version contains no rows for the requested test code."""


class RangeDirection(StrEnum):
    BELOW_LOWER = "BELOW_LOWER"
    ABOVE_UPPER = "ABOVE_UPPER"


class LabRangeRow(Protocol):
    @property
    def source_record_number(self) -> int: ...

    @property
    def unique_subject_id(self) -> str: ...

    @property
    def test_code(self) -> str: ...

    @property
    def standard_result(self) -> Decimal | None: ...

    @property
    def standard_unit(self) -> str | None: ...

    @property
    def lower_reference_limit(self) -> Decimal | None: ...

    @property
    def upper_reference_limit(self) -> Decimal | None: ...

    @property
    def baseline_flag(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class LabRangeEvidence:
    source_record_number: int
    unique_subject_id: str
    standard_result: Decimal
    standard_unit: str | None
    lower_reference_limit: Decimal
    upper_reference_limit: Decimal
    direction: RangeDirection
    baseline_flag: str | None


@dataclass(frozen=True, slots=True)
class LabRangeResult:
    method_version: str
    test_code: str
    total_rows: int
    eligible_rows: int
    excluded_rows: int
    below_lower_rows: int
    above_upper_rows: int
    subjects_with_out_of_range: int
    evidence: tuple[LabRangeEvidence, ...]
    evidence_truncated: bool

    @property
    def out_of_range_rows(self) -> int:
        return self.below_lower_rows + self.above_upper_rows


def calculate_lab_reference_range(rows: Iterable[LabRangeRow], test_code: str) -> LabRangeResult:
    """Compare numeric results to their own row's limits; never infer timing."""
    selected = sorted(
        (row for row in rows if row.test_code == test_code),
        key=lambda row: row.source_record_number,
    )
    if not selected:
        raise LabTestNotFoundError("The selected lab test is absent from this dataset version.")

    eligible = 0
    below = 0
    above = 0
    subjects: set[str] = set()
    evidence: list[LabRangeEvidence] = []
    for row in selected:
        value = row.standard_result
        lower = row.lower_reference_limit
        upper = row.upper_reference_limit
        if (
            value is None
            or lower is None
            or upper is None
            or not value.is_finite()
            or not lower.is_finite()
            or not upper.is_finite()
            or lower >= upper
        ):
            continue
        eligible += 1
        if value < lower:
            direction = RangeDirection.BELOW_LOWER
            below += 1
        elif value > upper:
            direction = RangeDirection.ABOVE_UPPER
            above += 1
        else:
            continue
        subjects.add(row.unique_subject_id)
        if len(evidence) < MAX_EVIDENCE_ROWS:
            evidence.append(
                LabRangeEvidence(
                    source_record_number=row.source_record_number,
                    unique_subject_id=row.unique_subject_id,
                    standard_result=value,
                    standard_unit=row.standard_unit,
                    lower_reference_limit=lower,
                    upper_reference_limit=upper,
                    direction=direction,
                    baseline_flag=row.baseline_flag,
                )
            )

    return LabRangeResult(
        method_version=METHOD_VERSION,
        test_code=test_code,
        total_rows=len(selected),
        eligible_rows=eligible,
        excluded_rows=len(selected) - eligible,
        below_lower_rows=below,
        above_upper_rows=above,
        subjects_with_out_of_range=len(subjects),
        evidence=tuple(evidence),
        evidence_truncated=below + above > len(evidence),
    )


async def calculate_stored_lab_reference_range(
    session: AsyncSession, dataset_version_id: UUID, test_code: str
) -> LabRangeResult:
    """Read only LB rows for one test and one immutable dataset version."""
    version_id = await session.scalar(
        select(DatasetVersion.id).where(DatasetVersion.id == dataset_version_id)
    )
    if version_id is None:
        raise DatasetVersionNotFoundError("The selected dataset version does not exist.")
    rows = (
        await session.scalars(
            select(LBResult)
            .where(
                LBResult.dataset_version_id == dataset_version_id, LBResult.test_code == test_code
            )
            .order_by(LBResult.source_record_number)
        )
    ).all()
    return calculate_lab_reference_range(rows, test_code)
