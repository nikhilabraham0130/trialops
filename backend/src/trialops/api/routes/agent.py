"""Endpoints for governed AI planning without automatic tool execution."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from trialops.agent.contracts import AnalysisPlan
from trialops.agent.orchestrator import (
    AgentPlanningError,
    AgentPlanningErrorCode,
    propose_analysis_plan,
)
from trialops.api.dependencies import DatabaseSession, PlanningModel
from trialops.datasets.models import DatasetVersion

router = APIRouter(prefix="/agent", tags=["agent"])


class PlanCreationRequest(BaseModel):
    """User question plus the dataset snapshot selected by the application."""

    question: Annotated[str, Field(min_length=1, max_length=2000)]
    dataset_version_id: UUID


def _planning_http_error(error: AgentPlanningError) -> HTTPException:
    """Map stable planning failures to safe HTTP responses."""
    status_by_code = {
        AgentPlanningErrorCode.INVALID_QUESTION: status.HTTP_422_UNPROCESSABLE_CONTENT,
        AgentPlanningErrorCode.MODEL_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
        AgentPlanningErrorCode.INVALID_MODEL_RESPONSE: status.HTTP_502_BAD_GATEWAY,
    }
    return HTTPException(
        status_code=status_by_code[error.code],
        detail={"code": error.code.value, "message": str(error)},
    )


@router.post(
    "/plans",
    response_model=AnalysisPlan,
    status_code=status.HTTP_201_CREATED,
    summary="Propose a confirmation-required analysis plan",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Dataset version not found"},
        status.HTTP_502_BAD_GATEWAY: {"description": "Invalid model response"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Planning model unavailable"},
    },
)
async def create_plan(
    request: PlanCreationRequest,
    session: DatabaseSession,
    model: PlanningModel,
) -> AnalysisPlan:
    """Validate the selected snapshot, then ask the model for an unexecuted plan."""
    version_id = await session.scalar(
        select(DatasetVersion.id).where(DatasetVersion.id == request.dataset_version_id)
    )
    if version_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "DATASET_VERSION_NOT_FOUND",
                "message": "The selected dataset version does not exist.",
            },
        )

    try:
        return await propose_analysis_plan(
            model,
            question=request.question,
            dataset_version_id=request.dataset_version_id,
        )
    except AgentPlanningError as exc:
        raise _planning_http_error(exc) from exc
