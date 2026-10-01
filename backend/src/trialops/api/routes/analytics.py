"""Read-only endpoints for deterministic clinical calculations."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from trialops.analytics.contracts import (
    AltAbnormalityResponse,
    SeriousAeIncidenceResponse,
    SevereAeIncidenceResponse,
    SubjectSafetySummaryResponse,
    to_alt_abnormality_response,
    to_serious_ae_incidence_response,
    to_severe_ae_incidence_response,
    to_subject_safety_summary_response,
)
from trialops.analytics.lab_abnormalities import calculate_stored_alt_gt_3x_uln
from trialops.analytics.serious_adverse_events import calculate_stored_serious_ae_incidence
from trialops.analytics.severe_adverse_events import calculate_stored_severe_ae_incidence
from trialops.analytics.subject_safety import (
    SubjectNotFoundError,
    get_stored_subject_safety_summary,
)
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


@router.get(
    "/{dataset_version_id}/analytics/severe-ae-incidence",
    response_model=SevereAeIncidenceResponse,
    summary="Count subjects with recorded severe AEs by actual treatment arm",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Dataset version not found"}},
)
async def get_severe_ae_incidence(
    dataset_version_id: UUID,
    session: DatabaseSession,
) -> SevereAeIncidenceResponse:
    """Return descriptive subject incidence without implying treatment emergence."""
    try:
        result = await calculate_stored_severe_ae_incidence(session, dataset_version_id)
    except DatasetVersionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DATASET_VERSION_NOT_FOUND", "message": str(exc)},
        ) from exc
    return to_severe_ae_incidence_response(dataset_version_id, result)


@router.get(
    "/{dataset_version_id}/analytics/serious-ae-incidence",
    response_model=SeriousAeIncidenceResponse,
    summary="Count subjects with source-flagged serious AEs by actual treatment arm",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Dataset version not found"}},
)
async def get_serious_ae_incidence(
    dataset_version_id: UUID, session: DatabaseSession
) -> SeriousAeIncidenceResponse:
    """Use AESER, not AESEV, for a descriptive seriousness calculation."""
    try:
        result = await calculate_stored_serious_ae_incidence(session, dataset_version_id)
    except DatasetVersionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DATASET_VERSION_NOT_FOUND", "message": str(exc)},
        ) from exc
    return to_serious_ae_incidence_response(dataset_version_id, result)


@router.get(
    "/{dataset_version_id}/analytics/subjects/{unique_subject_id}/safety-summary",
    response_model=SubjectSafetySummaryResponse,
    summary="Show source-linked AE and flagged laboratory records for one subject",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Version or subject not found"}},
)
async def get_subject_safety_summary(
    dataset_version_id: UUID,
    unique_subject_id: str,
    session: DatabaseSession,
) -> SubjectSafetySummaryResponse:
    """Return a descriptive cross-domain view from one immutable data cut."""
    try:
        result = await get_stored_subject_safety_summary(
            session, dataset_version_id, unique_subject_id
        )
    except DatasetVersionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DATASET_VERSION_NOT_FOUND", "message": str(exc)},
        ) from exc
    except SubjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SUBJECT_NOT_FOUND", "message": str(exc)},
        ) from exc
    return to_subject_safety_summary_response(dataset_version_id, result)
