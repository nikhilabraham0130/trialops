"""Persist and retrieve reproduction comparisons without rewriting analyses."""

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.models import AgentPlanRecord
from trialops.agent.queries import get_analysis_plan, validate_analysis_plan_record
from trialops.audit.service import append_audit_event
from trialops.lineage.models import ReproductionRunRecord
from trialops.lineage.reproduction import (
    ReproductionComparison,
    StoredReproductionRun,
    _canonical_bytes,
)


class ReproductionStorageErrorCode(StrEnum):
    PLAN_CHANGED = "PLAN_CHANGED"
    DATABASE_CONFLICT = "DATABASE_CONFLICT"


class ReproductionStorageError(RuntimeError):
    def __init__(self, code: ReproductionStorageErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def _to_stored(
    record: ReproductionRunRecord, comparison: ReproductionComparison
) -> StoredReproductionRun:
    return StoredReproductionRun(
        **comparison.model_dump(),
        id=record.id,
        created_at=record.created_at,
    )


async def store_reproduction_run(
    session: AsyncSession, comparison: ReproductionComparison
) -> StoredReproductionRun:
    """Lock the saved plan, recheck its result hash, then append one history row."""
    plan_record = await session.scalar(
        select(AgentPlanRecord).where(AgentPlanRecord.id == comparison.plan_id).with_for_update()
    )
    if plan_record is None:
        await session.rollback()
        raise ReproductionStorageError(
            ReproductionStorageErrorCode.PLAN_CHANGED,
            "The saved analysis changed before its reproduction could be recorded.",
        )
    plan = validate_analysis_plan_record(plan_record)
    current_hash = (
        hashlib.sha256(_canonical_bytes(plan.result.model_dump(mode="json"))).hexdigest()
        if plan.result is not None
        else None
    )
    if (
        plan.dataset_version_id != comparison.dataset_version_id
        or plan.tool_call.name != comparison.tool_name
        or current_hash != comparison.stored_result_sha256
    ):
        await session.rollback()
        raise ReproductionStorageError(
            ReproductionStorageErrorCode.PLAN_CHANGED,
            "The saved analysis changed before its reproduction could be recorded.",
        )

    record = ReproductionRunRecord(
        id=uuid4(),
        plan_id=comparison.plan_id,
        status=comparison.status,
        stored_result_sha256=comparison.stored_result_sha256,
        reproduced_result_sha256=comparison.reproduced_result_sha256,
        difference_count=comparison.difference_count,
        differences=[item.model_dump(mode="json") for item in comparison.differences],
        differences_truncated=comparison.differences_truncated,
        created_at=datetime.now(UTC),
    )
    session.add(record)
    append_audit_event(
        session,
        action="ANALYSIS_REPRODUCED",
        entity_type="agent_plan",
        entity_id=comparison.plan_id,
        details={"status": comparison.status, "reproduction_run_id": str(record.id)},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ReproductionStorageError(
            ReproductionStorageErrorCode.DATABASE_CONFLICT,
            "The reproduction comparison could not be stored safely.",
        ) from exc
    return _to_stored(record, comparison)


async def list_reproduction_runs(
    session: AsyncSession, plan_id: UUID
) -> tuple[StoredReproductionRun, ...]:
    """Read recorded comparisons in newest-first order for one validated plan."""
    plan = await get_analysis_plan(session, plan_id)
    records = (
        await session.scalars(
            select(ReproductionRunRecord)
            .where(ReproductionRunRecord.plan_id == plan_id)
            .order_by(ReproductionRunRecord.created_at.desc(), ReproductionRunRecord.id.desc())
        )
    ).all()
    return tuple(
        _to_stored(
            record,
            ReproductionComparison.model_validate(
                {
                    "plan_id": plan_id,
                    "dataset_version_id": plan.dataset_version_id,
                    "tool_name": plan.tool_call.name,
                    "status": record.status,
                    "stored_result_sha256": record.stored_result_sha256,
                    "reproduced_result_sha256": record.reproduced_result_sha256,
                    "difference_count": record.difference_count,
                    "differences": record.differences,
                    "differences_truncated": record.differences_truncated,
                }
            ),
        )
        for record in records
    )
