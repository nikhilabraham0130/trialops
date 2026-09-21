"""Endpoints for governed AI planning without automatic tool execution."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from trialops.agent.contracts import AnalysisExecution, AnalysisPlan
from trialops.agent.execution import (
    AgentExecutionError,
    AgentExecutionErrorCode,
    execute_confirmed_plan,
)
from trialops.agent.orchestrator import (
    AgentPlanningError,
    AgentPlanningErrorCode,
    propose_analysis_plan,
)
from trialops.agent.storage import AgentPlanStorageError, store_analysis_plan
from trialops.api.dependencies import DatabaseSession, PlanningModel
from trialops.datasets.models import DatasetVersion

router = APIRouter(prefix="/agent", tags=["agent"])


class PlanCreationRequest(BaseModel):
    """User question plus the dataset snapshot selected by the application."""

    question: Annotated[str, Field(min_length=1, max_length=2000)]
    dataset_version_id: UUID


class PlanConfirmationRequest(BaseModel):
    """An explicit decision to run the already stored plan."""

    confirmed: Literal[True]


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
        status.HTTP_409_CONFLICT: {"description": "Plan could not be stored"},
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
    await session.rollback()
    if version_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "DATASET_VERSION_NOT_FOUND",
                "message": "The selected dataset version does not exist.",
            },
        )

    try:
        plan = await propose_analysis_plan(
            model,
            question=request.question,
            dataset_version_id=request.dataset_version_id,
        )
    except AgentPlanningError as exc:
        raise _planning_http_error(exc) from exc

    try:
        await store_analysis_plan(session, plan)
    except AgentPlanStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code.value, "message": str(exc)},
        ) from exc
    return plan


@router.post(
    "/plans/{plan_id}/confirm",
    response_model=AnalysisExecution,
    summary="Confirm and execute a stored analysis plan",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Plan not found"},
        status.HTTP_409_CONFLICT: {"description": "Plan cannot be safely executed"},
    },
)
async def confirm_plan(
    plan_id: UUID,
    _request: PlanConfirmationRequest,
    session: DatabaseSession,
) -> AnalysisExecution:
    """Execute only the locked, server-controlled plan identified by its ID."""
    try:
        return await execute_confirmed_plan(session, plan_id)
    except AgentExecutionError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if exc.code is AgentExecutionErrorCode.PLAN_NOT_FOUND
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code.value, "message": str(exc)},
        ) from exc
