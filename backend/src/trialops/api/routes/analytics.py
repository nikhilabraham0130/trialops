"""Read-only endpoints for deterministic clinical calculations."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from trialops.analytics.contracts import (
    AltAbnormalityResponse,
    to_alt_abnormality_response,
)
from trialops.analytics.lab_abnormalities import calculate_stored_alt_gt_3x_uln
from trialops.api.dependencies import DatabaseSession
from trialops.validation.alt import DatasetVersionNotFoundError

router = APIRouter(prefix="/dataset-versions", tags=["analytics"])


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
    return to_alt_abnormality_response(dataset_version_id, result)
