"""Persistence workflow for verified interpretations of executed plans."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Never
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.contracts import PlanStatus
from trialops.agent.interpretation import (
    InterpretationError,
    InterpretationErrorCode,
    generate_grounded_interpretation,
)
from trialops.agent.interpretation_contracts import StoredInterpretation
from trialops.agent.interpretation_model import InterpretationModel
from trialops.agent.models import AgentPlanRecord
from trialops.agent.queries import (
    AgentPlanQueryError,
    AgentPlanQueryErrorCode,
    get_analysis_plan,
    validate_analysis_plan_record,
)


class InterpretationWorkflowErrorCode(StrEnum):
    """Stable reasons a plan interpretation cannot be created and stored."""

    PLAN_NOT_FOUND = "PLAN_NOT_FOUND"
    PLAN_NOT_EXECUTED = "PLAN_NOT_EXECUTED"
    INTERPRETATION_EXISTS = "INTERPRETATION_EXISTS"
    INVALID_STORED_PLAN = "INVALID_STORED_PLAN"
    PLAN_CHANGED = "PLAN_CHANGED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    INVALID_MODEL_RESPONSE = "INVALID_MODEL_RESPONSE"
    UNGROUNDED_NUMERIC_CLAIM = "UNGROUNDED_NUMERIC_CLAIM"
    DATABASE_CONFLICT = "DATABASE_CONFLICT"


class InterpretationWorkflowError(RuntimeError):
    """Safe interpretation failure for the application and HTTP layers."""

    def __init__(self, code: InterpretationWorkflowErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def _translate_query_error(error: AgentPlanQueryError) -> InterpretationWorkflowError:
    code = (
        InterpretationWorkflowErrorCode.PLAN_NOT_FOUND
        if error.code is AgentPlanQueryErrorCode.PLAN_NOT_FOUND
        else InterpretationWorkflowErrorCode.INVALID_STORED_PLAN
    )
    return InterpretationWorkflowError(code, str(error))


def _translate_model_error(error: InterpretationError) -> InterpretationWorkflowError:
    code_by_interpretation_error = {
        InterpretationErrorCode.MODEL_UNAVAILABLE: (
            InterpretationWorkflowErrorCode.MODEL_UNAVAILABLE
        ),
        InterpretationErrorCode.INVALID_MODEL_RESPONSE: (
            InterpretationWorkflowErrorCode.INVALID_MODEL_RESPONSE
        ),
        InterpretationErrorCode.UNGROUNDED_NUMERIC_CLAIM: (
            InterpretationWorkflowErrorCode.UNGROUNDED_NUMERIC_CLAIM
        ),
    }
    return InterpretationWorkflowError(code_by_interpretation_error[error.code], str(error))


async def _reject_after_lock(
    session: AsyncSession,
    code: InterpretationWorkflowErrorCode,
    message: str,
) -> Never:
    """Release the plan row lock before returning a controlled failure."""
    await session.rollback()
    raise InterpretationWorkflowError(code, message)


async def create_verified_plan_interpretation(
    session: AsyncSession,
    model: InterpretationModel,
    plan_id: UUID,
) -> StoredInterpretation:
    """Generate outside a transaction, then lock and persist against unchanged inputs."""
    try:
        original = await get_analysis_plan(session, plan_id)
    except AgentPlanQueryError as exc:
        await session.rollback()
        raise _translate_query_error(exc) from exc
    await session.rollback()

    if original.status is not PlanStatus.EXECUTED or original.result is None:
        raise InterpretationWorkflowError(
            InterpretationWorkflowErrorCode.PLAN_NOT_EXECUTED,
            "The analysis plan must be executed before it can be interpreted.",
        )
    if original.interpretation is not None:
        raise InterpretationWorkflowError(
            InterpretationWorkflowErrorCode.INTERPRETATION_EXISTS,
            "The analysis plan already has a verified interpretation.",
        )

    try:
        verified = await generate_grounded_interpretation(
            model,
            question=original.question,
            purpose=original.purpose,
            result=original.result,
        )
    except InterpretationError as exc:
        raise _translate_model_error(exc) from exc

    stored = StoredInterpretation(
        summary=verified.summary,
        numeric_claims=verified.numeric_claims,
        grounding_status=verified.grounding_status,
        prompt_version=verified.prompt_version,
        model_id=verified.model_id,
        generated_at=datetime.now(UTC),
    )

    record = await session.scalar(
        select(AgentPlanRecord).where(AgentPlanRecord.id == plan_id).with_for_update()
    )
    if record is None:
        await _reject_after_lock(
            session,
            InterpretationWorkflowErrorCode.PLAN_NOT_FOUND,
            "The requested analysis plan no longer exists.",
        )

    try:
        current = validate_analysis_plan_record(record)
    except AgentPlanQueryError as exc:
        await session.rollback()
        raise _translate_query_error(exc) from exc

    if current.interpretation is not None:
        await _reject_after_lock(
            session,
            InterpretationWorkflowErrorCode.INTERPRETATION_EXISTS,
            "The analysis plan already has a verified interpretation.",
        )
    if current != original:
        await _reject_after_lock(
            session,
            InterpretationWorkflowErrorCode.PLAN_CHANGED,
            "The analysis plan changed while its interpretation was being generated.",
        )

    record.interpretation = stored.model_dump(mode="json")
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise InterpretationWorkflowError(
            InterpretationWorkflowErrorCode.DATABASE_CONFLICT,
            "The verified interpretation could not be stored safely.",
        ) from exc
    return stored
