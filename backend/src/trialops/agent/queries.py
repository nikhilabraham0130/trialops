"""Validated read access to persisted agent plans."""

from enum import StrEnum
from typing import Never
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.contracts import (
    AltThresholdToolInput,
    AnalysisPlanDetails,
    ApprovedToolCall,
    ApprovedToolName,
    PlanStatus,
)
from trialops.agent.interpretation_contracts import StoredInterpretation
from trialops.agent.models import AgentPlanRecord
from trialops.analytics.contracts import AltAbnormalityResponse


class AgentPlanQueryErrorCode(StrEnum):
    """Stable reasons a saved plan cannot be returned."""

    PLAN_NOT_FOUND = "PLAN_NOT_FOUND"
    INVALID_STORED_PLAN = "INVALID_STORED_PLAN"


class AgentPlanQueryError(RuntimeError):
    """Raised when a requested plan is missing or internally inconsistent."""

    def __init__(self, code: AgentPlanQueryErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def _invalid_stored_plan(message: str) -> Never:
    """Reject inconsistent database state without exposing stored contents."""
    raise AgentPlanQueryError(AgentPlanQueryErrorCode.INVALID_STORED_PLAN, message)


def validate_analysis_plan_record(record: AgentPlanRecord) -> AnalysisPlanDetails:
    """Rebuild one ORM record only when all stored fields agree."""
    try:
        arguments = AltThresholdToolInput.model_validate(record.tool_arguments)
    except ValidationError as exc:
        raise AgentPlanQueryError(
            AgentPlanQueryErrorCode.INVALID_STORED_PLAN,
            "The stored analysis plan contains invalid tool arguments.",
        ) from exc

    if (
        record.tool_name != ApprovedToolName.CALCULATE_ALT_GT_3X_ULN
        or arguments.dataset_version_id != record.dataset_version_id
    ):
        _invalid_stored_plan("The stored analysis plan does not match an approved tool invocation.")

    try:
        result = (
            AltAbnormalityResponse.model_validate(record.result)
            if record.result is not None
            else None
        )
    except ValidationError as exc:
        raise AgentPlanQueryError(
            AgentPlanQueryErrorCode.INVALID_STORED_PLAN,
            "The stored analysis result has an invalid structure.",
        ) from exc

    if result is not None and result.dataset_version_id != record.dataset_version_id:
        _invalid_stored_plan("The stored result does not match the plan's dataset version.")

    if record.status is PlanStatus.EXECUTED and (result is None or record.executed_at is None):
        _invalid_stored_plan("The executed plan is missing its result or execution time.")

    if record.status is PlanStatus.AWAITING_CONFIRMATION and (
        result is not None or record.executed_at is not None
    ):
        _invalid_stored_plan("The unexecuted plan unexpectedly contains execution output.")

    try:
        interpretation = (
            StoredInterpretation.model_validate(record.interpretation)
            if record.interpretation is not None
            else None
        )
    except ValidationError as exc:
        raise AgentPlanQueryError(
            AgentPlanQueryErrorCode.INVALID_STORED_PLAN,
            "The stored interpretation has an invalid structure.",
        ) from exc

    if interpretation is not None and record.status is not PlanStatus.EXECUTED:
        _invalid_stored_plan("Only an executed plan may contain an interpretation.")

    try:
        return AnalysisPlanDetails(
            id=record.id,
            question=record.question,
            dataset_version_id=record.dataset_version_id,
            purpose=record.purpose,
            status=record.status,
            confirmation_required=record.status is PlanStatus.AWAITING_CONFIRMATION,
            tool_call=ApprovedToolCall(
                name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
                arguments=arguments,
            ),
            result=result,
            interpretation=interpretation,
            created_at=record.created_at,
            executed_at=record.executed_at,
        )
    except ValidationError as exc:
        raise AgentPlanQueryError(
            AgentPlanQueryErrorCode.INVALID_STORED_PLAN,
            "The stored analysis plan has an invalid structure.",
        ) from exc


async def get_analysis_plan(session: AsyncSession, plan_id: UUID) -> AnalysisPlanDetails:
    """Load and validate one server-controlled plan and its optional result."""
    record = await session.scalar(select(AgentPlanRecord).where(AgentPlanRecord.id == plan_id))
    if record is None:
        raise AgentPlanQueryError(
            AgentPlanQueryErrorCode.PLAN_NOT_FOUND,
            "The requested analysis plan does not exist.",
        )
    return validate_analysis_plan_record(record)
