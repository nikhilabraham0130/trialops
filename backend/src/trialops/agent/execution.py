"""Confirmation-gated execution of persisted, approved agent plans."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Never
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.contracts import (
    AltThresholdToolInput,
    AnalysisExecution,
    ApprovedToolName,
    PlanStatus,
    SubjectSafetyToolInput,
)
from trialops.agent.models import AgentPlanRecord
from trialops.analytics.contracts import (
    AltAbnormalityResponse,
    SevereAeIncidenceResponse,
    SubjectSafetySummaryResponse,
    to_alt_abnormality_response,
    to_severe_ae_incidence_response,
    to_subject_safety_summary_response,
)
from trialops.analytics.lab_abnormalities import calculate_stored_alt_gt_3x_uln
from trialops.analytics.severe_adverse_events import calculate_stored_severe_ae_incidence
from trialops.analytics.subject_safety import (
    SubjectNotFoundError,
    get_stored_subject_safety_summary,
)
from trialops.validation.alt import DatasetVersionNotFoundError


class AgentExecutionErrorCode(StrEnum):
    """Stable reasons a stored plan cannot be executed."""

    PLAN_NOT_FOUND = "PLAN_NOT_FOUND"
    PLAN_NOT_CONFIRMABLE = "PLAN_NOT_CONFIRMABLE"
    INVALID_STORED_PLAN = "INVALID_STORED_PLAN"
    DATABASE_CONFLICT = "DATABASE_CONFLICT"


class AgentExecutionError(RuntimeError):
    """Raised when confirmation cannot safely produce one execution."""

    def __init__(self, code: AgentExecutionErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


async def _reject_plan(
    session: AsyncSession,
    code: AgentExecutionErrorCode,
    message: str,
) -> Never:
    """Release the row lock before returning a controlled rejection."""
    await session.rollback()
    raise AgentExecutionError(code, message)


async def execute_confirmed_plan(
    session: AsyncSession,
    plan_id: UUID,
) -> AnalysisExecution:
    """Lock, validate, execute, and persist one confirmation-required plan."""
    record = await session.scalar(
        select(AgentPlanRecord).where(AgentPlanRecord.id == plan_id).with_for_update()
    )
    if record is None:
        await _reject_plan(
            session,
            AgentExecutionErrorCode.PLAN_NOT_FOUND,
            "The requested analysis plan does not exist.",
        )

    if record.status != PlanStatus.AWAITING_CONFIRMATION:
        await _reject_plan(
            session,
            AgentExecutionErrorCode.PLAN_NOT_CONFIRMABLE,
            "The analysis plan is no longer awaiting confirmation.",
        )

    try:
        if record.tool_name is ApprovedToolName.GET_SUBJECT_SAFETY_SUMMARY:
            arguments: AltThresholdToolInput | SubjectSafetyToolInput = (
                SubjectSafetyToolInput.model_validate(record.tool_arguments)
            )
        else:
            arguments = AltThresholdToolInput.model_validate(record.tool_arguments)
    except ValidationError as exc:
        await session.rollback()
        raise AgentExecutionError(
            AgentExecutionErrorCode.INVALID_STORED_PLAN,
            "The stored analysis plan contains invalid tool arguments.",
        ) from exc

    if (
        record.tool_name
        not in {
            ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
            ApprovedToolName.COMPARE_SEVERE_AE_INCIDENCE,
            ApprovedToolName.GET_SUBJECT_SAFETY_SUMMARY,
        }
        or arguments.dataset_version_id != record.dataset_version_id
    ):
        await _reject_plan(
            session,
            AgentExecutionErrorCode.INVALID_STORED_PLAN,
            "The stored analysis plan does not match an approved tool invocation.",
        )

    try:
        structured_result: (
            AltAbnormalityResponse | SevereAeIncidenceResponse | SubjectSafetySummaryResponse
        )
        if record.tool_name is ApprovedToolName.CALCULATE_ALT_GT_3X_ULN:
            result = await calculate_stored_alt_gt_3x_uln(session, record.dataset_version_id)
            structured_result = to_alt_abnormality_response(record.dataset_version_id, result)
        elif record.tool_name is ApprovedToolName.COMPARE_SEVERE_AE_INCIDENCE:
            severe_result = await calculate_stored_severe_ae_incidence(
                session, record.dataset_version_id
            )
            structured_result = to_severe_ae_incidence_response(
                record.dataset_version_id, severe_result
            )
        elif record.tool_name is ApprovedToolName.GET_SUBJECT_SAFETY_SUMMARY:
            if not isinstance(arguments, SubjectSafetyToolInput):
                await _reject_plan(
                    session,
                    AgentExecutionErrorCode.INVALID_STORED_PLAN,
                    "The stored subject plan has invalid arguments.",
                )
            subject_result = await get_stored_subject_safety_summary(
                session, record.dataset_version_id, arguments.subject_id
            )
            structured_result = to_subject_safety_summary_response(
                record.dataset_version_id, subject_result
            )
        else:
            await _reject_plan(
                session,
                AgentExecutionErrorCode.INVALID_STORED_PLAN,
                "The stored analysis plan requests an unsupported tool.",
            )
    except (DatasetVersionNotFoundError, SubjectNotFoundError) as exc:
        await session.rollback()
        raise AgentExecutionError(
            AgentExecutionErrorCode.INVALID_STORED_PLAN,
            "The stored analysis plan references an unavailable dataset version.",
        ) from exc

    execution = AnalysisExecution(
        plan_id=record.id,
        status=PlanStatus.EXECUTED,
        tool_name=record.tool_name,
        result=structured_result,
    )
    record.status = PlanStatus.EXECUTED
    record.result = structured_result.model_dump(mode="json")
    record.executed_at = datetime.now(UTC)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AgentExecutionError(
            AgentExecutionErrorCode.DATABASE_CONFLICT,
            "The analysis result could not be stored safely.",
        ) from exc

    return execution
