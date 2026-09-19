"""Read-only endpoints for deterministic clinical calculations."""

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from trialops.analytics.lab_abnormalities import (
    AltAbnormalityResult,
    TimingClassification,
    calculate_stored_alt_gt_3x_uln,
)
from trialops.api.dependencies import DatabaseSession
from trialops.validation.alt import DatasetVersionNotFoundError
from trialops.validation.findings import FindingSeverity

router = APIRouter(prefix="/dataset-versions", tags=["analytics"])


class ValidationFindingResponse(BaseModel):
    """One machine-readable reason a source row was excluded or blocked."""

    rule_code: str
    severity: FindingSeverity
    domain: str
    source_record_number: int | None
    message: str


class AltExceedanceResponse(BaseModel):
    """Source evidence for one ALT result above three times its upper limit."""

    source_record_number: int
    unique_subject_id: str
    standard_result: Decimal
    upper_reference_limit: Decimal
    threshold: Decimal
    timing: TimingClassification


class AltAbnormalityResponse(BaseModel):
    """Structured output of one version-specific ALT threshold calculation."""

    dataset_version_id: UUID
    method_version: str
    threshold_multiplier: Decimal
    alt_row_count: int
    eligible_row_count: int
    excluded_row_count: int
    qualifying_measurement_count: int
    subjects_with_qualifying_measurement: int
    exceedances: tuple[AltExceedanceResponse, ...]
    findings: tuple[ValidationFindingResponse, ...]
    timing_limitation: str


def _to_response(dataset_version_id: UUID, result: AltAbnormalityResult) -> AltAbnormalityResponse:
    """Convert the domain result into the stable public HTTP contract."""
    return AltAbnormalityResponse(
        dataset_version_id=dataset_version_id,
        method_version=result.method_version,
        threshold_multiplier=result.threshold_multiplier,
        alt_row_count=result.alt_row_count,
        eligible_row_count=result.eligible_row_count,
        excluded_row_count=result.excluded_row_count,
        qualifying_measurement_count=result.exceedance_count,
        subjects_with_qualifying_measurement=result.subjects_with_exceedance,
        exceedances=tuple(
            AltExceedanceResponse.model_validate(item, from_attributes=True)
            for item in result.exceedances
        ),
        findings=tuple(
            ValidationFindingResponse.model_validate(item, from_attributes=True)
            for item in result.findings
        ),
        timing_limitation=(
            "A blank baseline flag means not identified as baseline; it does not prove "
            "collection occurred after treatment began."
        ),
    )


@router.get(
    "/{dataset_version_id}/analytics/alt-gt-3x-uln",
    response_model=AltAbnormalityResponse,
    summary="Calculate ALT results above three times the upper reference limit",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Dataset version not found"}},
)
async def get_alt_gt_3x_uln(
    dataset_version_id: UUID,
    session: DatabaseSession,
) -> AltAbnormalityResponse:
    """Return a deterministic result without creating a reviewed analysis record."""
    try:
        result = await calculate_stored_alt_gt_3x_uln(session, dataset_version_id)
    except DatasetVersionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "DATASET_VERSION_NOT_FOUND",
                "message": str(exc),
            },
        ) from exc
    return _to_response(dataset_version_id, result)
