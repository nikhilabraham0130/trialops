"""Analysis-specific prerequisites for ALT laboratory measurements."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.datasets.models import DatasetVersion, LBResult
from trialops.validation.findings import FindingSeverity, ValidationFinding


class AltMeasurement(Protocol):
    """Fields required to assess an ALT row without coupling rules to the ORM."""

    @property
    def source_record_number(self) -> int: ...

    @property
    def test_code(self) -> str: ...

    @property
    def standard_result(self) -> Decimal | None: ...

    @property
    def upper_reference_limit(self) -> Decimal | None: ...


@dataclass(frozen=True, slots=True)
class AltPrerequisiteReport:
    """Counts and row-level reasons an ALT measurement cannot enter analysis."""

    alt_row_count: int
    eligible_row_count: int
    findings: tuple[ValidationFinding, ...]


class DatasetVersionNotFoundError(ValueError):
    """Raised when a caller requests validation for an unknown data snapshot."""


def check_alt_prerequisites(rows: Iterable[AltMeasurement]) -> AltPrerequisiteReport:
    """Check only prerequisites for ALT >3xULN; do not calculate abnormalities."""
    alt_row_count = 0
    eligible_row_count = 0
    findings: list[ValidationFinding] = []

    for row in rows:
        if row.test_code != "ALT":
            continue

        alt_row_count += 1
        valid_result = row.standard_result is not None and row.standard_result.is_finite()
        valid_upper_limit = (
            row.upper_reference_limit is not None
            and row.upper_reference_limit.is_finite()
            and row.upper_reference_limit > 0
        )

        if not valid_result:
            findings.append(
                ValidationFinding(
                    rule_code="ALT_RESULT_MISSING_OR_INVALID",
                    severity=FindingSeverity.WARNING,
                    domain="LB",
                    source_record_number=row.source_record_number,
                    message="ALT result is missing or not a finite number.",
                )
            )
        if not valid_upper_limit:
            findings.append(
                ValidationFinding(
                    rule_code="ALT_UPPER_LIMIT_MISSING_OR_INVALID",
                    severity=FindingSeverity.WARNING,
                    domain="LB",
                    source_record_number=row.source_record_number,
                    message="ALT upper reference limit must be a positive finite number.",
                )
            )
        if valid_result and valid_upper_limit:
            eligible_row_count += 1

    if alt_row_count == 0:
        findings.append(
            ValidationFinding(
                rule_code="ALT_RESULTS_MISSING",
                severity=FindingSeverity.BLOCKING,
                domain="LB",
                source_record_number=None,
                message="This dataset version contains no ALT laboratory results.",
            )
        )

    return AltPrerequisiteReport(alt_row_count, eligible_row_count, tuple(findings))


async def check_stored_alt_prerequisites(
    session: AsyncSession, dataset_version_id: UUID
) -> AltPrerequisiteReport:
    """Read one exact version's ALT rows and apply the deterministic rule."""
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
    return check_alt_prerequisites(rows)
