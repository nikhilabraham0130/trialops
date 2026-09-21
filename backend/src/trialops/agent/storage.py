"""Persistence boundary for confirmation-required agent plans."""

from enum import StrEnum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.contracts import AnalysisPlan
from trialops.agent.models import AgentPlanRecord


class AgentPlanStorageErrorCode(StrEnum):
    """Stable reasons a generated plan could not be retained."""

    DATABASE_CONFLICT = "DATABASE_CONFLICT"


class AgentPlanStorageError(RuntimeError):
    """Raised when PostgreSQL rejects a plan before confirmation."""

    def __init__(self, code: AgentPlanStorageErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


async def store_analysis_plan(session: AsyncSession, plan: AnalysisPlan) -> None:
    """Commit the exact plan that the user will later confirm."""
    record = AgentPlanRecord(
        id=plan.id,
        dataset_version_id=plan.dataset_version_id,
        question=plan.question,
        purpose=plan.purpose,
        status=plan.status,
        tool_name=plan.tool_call.name,
        tool_arguments=plan.tool_call.arguments.model_dump(mode="json"),
    )
    session.add(record)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AgentPlanStorageError(
            AgentPlanStorageErrorCode.DATABASE_CONFLICT,
            "The analysis plan could not be stored safely.",
        ) from exc
