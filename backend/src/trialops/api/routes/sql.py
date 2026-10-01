"""Controlled endpoint for human- or model-authored candidate clinical SQL."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from trialops.api.dependencies import DatabaseSession
from trialops.sql.execution import GovernedSQLResult, SQLExecutionError, run_governed_sql
from trialops.sql.policy import SQLPolicyError
from trialops.validation.alt import DatasetVersionNotFoundError

router = APIRouter(prefix="/dataset-versions", tags=["governed-sql"])


class SQLQueryRequest(BaseModel):
    candidate_sql: str = Field(min_length=1, max_length=4000)


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
