"""Endpoints for governed AI planning and confirmation-gated execution."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from trialops.agent.contracts import AnalysisExecution, AnalysisPlan, AnalysisPlanDetails
from trialops.agent.execution import (
    AgentExecutionError,
    AgentExecutionErrorCode,
    execute_confirmed_plan,
)
from trialops.agent.interpretation_contracts import StoredInterpretation
from trialops.agent.interpretation_workflow import (
    InterpretationWorkflowError,
    InterpretationWorkflowErrorCode,
    create_verified_plan_interpretation,
)
from trialops.agent.orchestrator import (
    AgentPlanningError,
    AgentPlanningErrorCode,
    propose_analysis_plan,
)
from trialops.agent.queries import (
    AgentPlanQueryError,
    AgentPlanQueryErrorCode,
    get_analysis_plan,
)
from trialops.agent.storage import AgentPlanStorageError, store_analysis_plan
from trialops.api.dependencies import DatabaseSession, InterpretationProvider, PlanningModel
from trialops.datasets.models import DatasetVersion
from trialops.governance.contracts import GovernanceEvaluation
from trialops.governance.policies import evaluate_analysis_governance
from trialops.lineage.reproduction import (
    ReproductionError,
    StoredReproductionRun,
    reproduce_analysis_plan,
)
from trialops.lineage.storage import (
    ReproductionStorageError,
    list_reproduction_runs,
    store_reproduction_run,
)

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
        AgentPlanningErrorCode.ANALYSIS_NOT_SUPPORTED: status.HTTP_422_UNPROCESSABLE_CONTENT,
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


@router.get(
    "/plans/{plan_id}",
    response_model=AnalysisPlanDetails,
    summary="Retrieve a stored analysis plan",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Plan not found"},
        status.HTTP_409_CONFLICT: {"description": "Stored plan is inconsistent"},
    },
)
async def read_plan(plan_id: UUID, session: DatabaseSession) -> AnalysisPlanDetails:
    """Return validated plan state from PostgreSQL without rerunning its tool."""
    try:
        return await get_analysis_plan(session, plan_id)
    except AgentPlanQueryError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if exc.code is AgentPlanQueryErrorCode.PLAN_NOT_FOUND
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code.value, "message": str(exc)},
        ) from exc


@router.get(
    "/plans/{plan_id}/governance",
    response_model=GovernanceEvaluation,
    summary="Evaluate the current governance state of a stored plan",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Plan not found"},
        status.HTTP_409_CONFLICT: {"description": "Stored plan is inconsistent"},
    },
)
async def read_plan_governance(plan_id: UUID, session: DatabaseSession) -> GovernanceEvaluation:
    """Apply deterministic policy rules to the latest persisted plan state."""
    try:
        plan = await get_analysis_plan(session, plan_id)
    except AgentPlanQueryError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if exc.code is AgentPlanQueryErrorCode.PLAN_NOT_FOUND
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code.value, "message": str(exc)},
        ) from exc
    return evaluate_analysis_governance(plan)


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


@router.post(
    "/plans/{plan_id}/interpretation",
    response_model=StoredInterpretation,
    status_code=status.HTTP_201_CREATED,
    summary="Generate and store a numerically verified interpretation",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Plan not found"},
        status.HTTP_409_CONFLICT: {"description": "Plan cannot be interpreted"},
        status.HTTP_502_BAD_GATEWAY: {"description": "Model output failed verification"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Model unavailable"},
    },
)
async def create_interpretation(
    plan_id: UUID,
    session: DatabaseSession,
    model: InterpretationProvider,
) -> StoredInterpretation:
    """Store model prose only after deterministic numeric grounding succeeds."""
    try:
        return await create_verified_plan_interpretation(session, model, plan_id)
    except InterpretationWorkflowError as exc:
        if exc.code is InterpretationWorkflowErrorCode.PLAN_NOT_FOUND:
            status_code = status.HTTP_404_NOT_FOUND
        elif exc.code is InterpretationWorkflowErrorCode.MODEL_UNAVAILABLE:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif exc.code in {
            InterpretationWorkflowErrorCode.INVALID_MODEL_RESPONSE,
            InterpretationWorkflowErrorCode.UNGROUNDED_NUMERIC_CLAIM,
        }:
            status_code = status.HTTP_502_BAD_GATEWAY
        else:
            status_code = status.HTTP_409_CONFLICT
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code.value, "message": str(exc)},
        ) from exc


@router.post(
    "/plans/{plan_id}/reproduce",
    response_model=StoredReproductionRun,
    summary="Rerun and compare a saved deterministic analysis",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Plan not found"},
        status.HTTP_409_CONFLICT: {"description": "Plan or source cannot be reproduced"},
    },
)
async def reproduce_plan(plan_id: UUID, session: DatabaseSession) -> StoredReproductionRun:
    """Compare a new calculation, then append the verified comparison to history."""
    try:
        comparison = await reproduce_analysis_plan(session, plan_id)
        return await store_reproduction_run(session, comparison)
    except AgentPlanQueryError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if exc.code is AgentPlanQueryErrorCode.PLAN_NOT_FOUND
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code.value, "message": str(exc)},
        ) from exc
    except ReproductionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code.value, "message": str(exc)},
        ) from exc
    except ReproductionStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code.value, "message": str(exc)},
        ) from exc


@router.get(
    "/plans/{plan_id}/reproductions",
    response_model=tuple[StoredReproductionRun, ...],
    summary="List saved reproduction comparisons for one analysis",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Plan not found"}},
)
async def read_reproduction_history(
    plan_id: UUID, session: DatabaseSession
) -> tuple[StoredReproductionRun, ...]:
    """Return prior comparisons without rerunning the clinical calculation."""
    try:
        return await list_reproduction_runs(session, plan_id)
    except AgentPlanQueryError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if exc.code is AgentPlanQueryErrorCode.PLAN_NOT_FOUND
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code.value, "message": str(exc)},
        ) from exc
