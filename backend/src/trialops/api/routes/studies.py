"""Read-only study catalog endpoints."""

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from trialops.api.dependencies import DatabaseSession
from trialops.datasets.models import DatasetVersionStatus
from trialops.studies.queries import list_study_summaries

router = APIRouter(prefix="/studies", tags=["studies"])


class DatasetVersionSummaryResponse(BaseModel):
    """Dataset-version identity and normalized DM population size."""

    id: UUID
    version_label: str
    status: DatasetVersionStatus
    subject_count: int


class StudySummaryResponse(BaseModel):
    """Study identity and all registered dataset versions."""

    id: UUID
    study_oid: str
    title: str | None
    dataset_versions: tuple[DatasetVersionSummaryResponse, ...]


class StudyListResponse(BaseModel):
    """Complete study catalog returned to the frontend."""

    studies: tuple[StudySummaryResponse, ...]


@router.get(
    "",
    response_model=StudyListResponse,
    summary="List studies and normalized DM subject counts",
)
async def list_studies(session: DatabaseSession) -> StudyListResponse:
    """Return the read-only study catalog for the initial frontend slice."""
    summaries = await list_study_summaries(session)
    return StudyListResponse(
        studies=tuple(
            StudySummaryResponse.model_validate(summary, from_attributes=True)
            for summary in summaries
        )
    )
