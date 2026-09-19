"""Deterministic ALT threshold calculations with explicit evidence."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.datasets.models import DatasetVersion, LBResult
from trialops.validation.alt import DatasetVersionNotFoundError, check_alt_prerequisites
from trialops.validation.findings import ValidationFinding

METHOD_VERSION = "alt-gt-3x-uln/1.0"
THRESHOLD_MULTIPLIER = Decimal(3)


class AltAnalysisRow(Protocol):
    """Fields needed for ALT threshold classification and source evidence."""

    @property
    def source_record_number(self) -> int: ...

    @property
    def unique_subject_id(self) -> str: ...

    @property
    def test_code(self) -> str: ...

    @property
    def standard_result(self) -> Decimal | None: ...

    @property
    def upper_reference_limit(self) -> Decimal | None: ...

    @property
    def baseline_flag(self) -> str | None: ...


class TimingClassification(StrEnum):
    """What the stored LB baseline flag actually establishes."""

    BASELINE = "BASELINE"
    NOT_IDENTIFIED_AS_BASELINE = "NOT_IDENTIFIED_AS_BASELINE"


@dataclass(frozen=True, slots=True)
class AltExceedance:
    """Source-backed evidence for one ALT result above the fixed threshold."""

    source_record_number: int
    unique_subject_id: str
    standard_result: Decimal
    upper_reference_limit: Decimal
    threshold: Decimal
    timing: TimingClassification


@dataclass(frozen=True, slots=True)
class AltAbnormalityResult:
    """Structured result of the versioned ALT >3xULN calculation."""

    method_version: str
    threshold_multiplier: Decimal
    alt_row_count: int
    eligible_row_count: int
    excluded_row_count: int
    subjects_with_exceedance: int
    exceedances: tuple[AltExceedance, ...]
    findings: tuple[ValidationFinding, ...]

    @property
    def exceedance_count(self) -> int:
        """Return the number of measurements, not the number of subjects."""
        return len(self.exceedances)


def calculate_alt_gt_3x_uln(rows: Iterable[AltAnalysisRow]) -> AltAbnormalityResult:
    """Classify eligible ALT rows using a strict greater-than threshold."""
    row_batch = tuple(rows)
    prerequisites = check_alt_prerequisites(row_batch)
    exceedances: list[AltExceedance] = []

    for row in row_batch:
        if row.test_code != "ALT":
            continue
        if (
            row.standard_result is None
            or not row.standard_result.is_finite()
            or row.upper_reference_limit is None
            or not row.upper_reference_limit.is_finite()
            or row.upper_reference_limit <= 0
        ):
            continue

        threshold = THRESHOLD_MULTIPLIER * row.upper_reference_limit
        if row.standard_result > threshold:
            exceedances.append(
                AltExceedance(
                    source_record_number=row.source_record_number,
                    unique_subject_id=row.unique_subject_id,
                    standard_result=row.standard_result,
                    upper_reference_limit=row.upper_reference_limit,
                    threshold=threshold,
                    timing=(
                        TimingClassification.BASELINE
                        if row.baseline_flag == "Y"
                        else TimingClassification.NOT_IDENTIFIED_AS_BASELINE
                    ),
                )
            )

    return AltAbnormalityResult(
        method_version=METHOD_VERSION,
        threshold_multiplier=THRESHOLD_MULTIPLIER,
        alt_row_count=prerequisites.alt_row_count,
        eligible_row_count=prerequisites.eligible_row_count,
        excluded_row_count=prerequisites.alt_row_count - prerequisites.eligible_row_count,
        subjects_with_exceedance=len({exceedance.unique_subject_id for exceedance in exceedances}),
        exceedances=tuple(exceedances),
        findings=prerequisites.findings,
    )


async def calculate_stored_alt_gt_3x_uln(
    session: AsyncSession, dataset_version_id: UUID
) -> AltAbnormalityResult:
    """Calculate ALT threshold results from one explicitly selected snapshot."""
    version_id = await session.scalar(
        select(DatasetVersion.id).where(DatasetVersion.id == dataset_version_id)
    )
    if version_id is None:
        raise DatasetVersionNotFoundError("The selected dataset version does not exist.")

    rows = (
        await session.scalars(
            select(LBResult)
            .where(LBResult.dataset_version_id == dataset_version_id, LBResult.test_code == "ALT")
            .order_by(LBResult.source_record_number)
        )
    ).all()
    return calculate_alt_gt_3x_uln(rows)
