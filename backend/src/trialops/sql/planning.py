"""Turn a natural-language question into a validated, unexecuted SQL proposal."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from trialops.sql.model import SQLModel, SQLModelError, SQLModelRequest
from trialops.sql.policy import APPROVED_COLUMNS, SQLPolicyError, validate_clinical_sql


class SQLPlanningErrorCode(StrEnum):
    MODEL_UNAVAILABLE = "SQL_MODEL_UNAVAILABLE"
    INVALID_MODEL_RESPONSE = "SQL_INVALID_MODEL_RESPONSE"
    QUERY_NOT_SUPPORTED = "SQL_QUERY_NOT_SUPPORTED"


class SQLPlanningError(ValueError):
    def __init__(self, code: SQLPlanningErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class _ModelSQLProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_sql: str | None = Field(default=None, max_length=4000)
    purpose: str = Field(min_length=1, max_length=500)

    @field_validator("purpose")
    @classmethod
    def reject_blank_purpose(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("purpose must contain visible text")
        return value


class SQLProposal(BaseModel):
    dataset_version_id: UUID
    question: str
    purpose: str
    validated_sql: str
    confirmation_required: bool = True


async def propose_clinical_sql(
    model: SQLModel, *, dataset_version_id: UUID, question: str
) -> SQLProposal:
    """Accept only SQL that passes the exact same policy as execution."""
    try:
        response_json = await model.generate_sql_json(
            SQLModelRequest(
                question=question,
                approved_schema={
                    name: tuple(sorted(columns)) for name, columns in APPROVED_COLUMNS.items()
                },
            )
        )
    except SQLModelError as exc:
        raise SQLPlanningError(
            SQLPlanningErrorCode.MODEL_UNAVAILABLE, "The SQL planning model is unavailable."
        ) from exc
    try:
        proposal = _ModelSQLProposal.model_validate_json(response_json)
    except ValidationError as exc:
        raise SQLPlanningError(
            SQLPlanningErrorCode.INVALID_MODEL_RESPONSE,
            "The SQL planning model returned an invalid proposal.",
        ) from exc
    if proposal.candidate_sql is None:
        raise SQLPlanningError(
            SQLPlanningErrorCode.QUERY_NOT_SUPPORTED,
            "The question cannot be answered using one approved clinical view.",
        )
    try:
        validated_sql = validate_clinical_sql(proposal.candidate_sql)
    except SQLPolicyError as exc:
        raise SQLPlanningError(
            SQLPlanningErrorCode.INVALID_MODEL_RESPONSE,
            "The SQL planning model proposed a query outside the approved policy.",
        ) from exc
    return SQLProposal(
        dataset_version_id=dataset_version_id,
        question=question,
        purpose=proposal.purpose,
        validated_sql=validated_sql,
    )
