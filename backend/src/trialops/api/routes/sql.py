"""Controlled endpoint for human- or model-authored candidate clinical SQL."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from trialops.api.dependencies import DatabaseSession, SQLPlanningModel
from trialops.datasets.models import DatasetVersion
from trialops.sql.execution import GovernedSQLResult, SQLExecutionError, run_governed_sql
from trialops.sql.planning import (
    SQLPlanningError,
    SQLPlanningErrorCode,
    SQLProposal,
    propose_clinical_sql,
)
from trialops.sql.policy import SQLPolicyError
from trialops.validation.alt import DatasetVersionNotFoundError

router = APIRouter(prefix="/dataset-versions", tags=["governed-sql"])


class SQLQueryRequest(BaseModel):
    candidate_sql: str = Field(min_length=1, max_length=4000)


class SQLProposalRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@router.post(
    "/{dataset_version_id}/sql/proposals",
    response_model=SQLProposal,
    summary="Draft but do not execute a validated clinical SQL query",
)
async def propose_sql(
    dataset_version_id: UUID,
    request: SQLProposalRequest,
    session: DatabaseSession,
    model: SQLPlanningModel,
) -> SQLProposal:
    """Show an approved candidate for a separate, explicit execution request."""
    if not request.question.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_QUESTION", "message": "A visible question is required."},
        )
    version_id = await session.scalar(
        select(DatasetVersion.id).where(DatasetVersion.id == dataset_version_id)
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
        return await propose_clinical_sql(
            model, dataset_version_id=dataset_version_id, question=request.question
        )
    except SQLPlanningError as exc:
        status_code = {
            SQLPlanningErrorCode.MODEL_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
            SQLPlanningErrorCode.INVALID_MODEL_RESPONSE: status.HTTP_502_BAD_GATEWAY,
            SQLPlanningErrorCode.QUERY_NOT_SUPPORTED: status.HTTP_422_UNPROCESSABLE_CONTENT,
        }[exc.code]
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code.value, "message": str(exc)},
        ) from exc


@router.post(
    "/{dataset_version_id}/sql",
    response_model=GovernedSQLResult,
    summary="Validate and run one restricted read-only clinical SELECT",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Dataset version not found"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "SQL policy or query failure"},
    },
)
async def execute_clinical_sql(
    dataset_version_id: UUID,
    request: SQLQueryRequest,
    session: DatabaseSession,
) -> GovernedSQLResult:
    """Never expose credentials or unrestricted relations to a candidate query."""
    try:
        return await run_governed_sql(session, dataset_version_id, request.candidate_sql)
    except DatasetVersionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DATASET_VERSION_NOT_FOUND", "message": str(exc)},
        ) from exc
    except (SQLPolicyError, SQLExecutionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": exc.code.value, "message": str(exc)},
        ) from exc
