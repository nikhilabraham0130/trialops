"""Tests for confirmation-gated execution of persisted agent plans."""

import asyncio
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.contracts import ApprovedToolName, PlanStatus
from trialops.agent.execution import (
    AgentExecutionError,
    AgentExecutionErrorCode,
    execute_confirmed_plan,
)
from trialops.agent.models import AgentPlanRecord
from trialops.analytics.lab_abnormalities import AltAbnormalityResult
from trialops.validation.alt import DatasetVersionNotFoundError


class _FakeSession:
    def __init__(
        self,
        record: AgentPlanRecord | None,
        *,
        commit_error: IntegrityError | None = None,
    ) -> None:
        self.record = record
        self.commit_error = commit_error
        self.statements: list[object] = []
        self.commit_calls = 0
        self.rollback_calls = 0

    async def scalar(self, statement: object) -> AgentPlanRecord | None:
        self.statements.append(statement)
        return self.record

    async def commit(self) -> None:
        self.commit_calls += 1
        if self.commit_error is not None:
            raise self.commit_error

    async def rollback(self) -> None:
        self.rollback_calls += 1


def _record(
    *,
    status: PlanStatus = PlanStatus.AWAITING_CONFIRMATION,
    arguments_version_id: UUID | None = None,
) -> AgentPlanRecord:
    dataset_version_id = uuid4()
    return AgentPlanRecord(
        id=uuid4(),
        dataset_version_id=dataset_version_id,
        question="Check ALT.",
        purpose="Use the approved deterministic ALT calculation.",
        status=status,
        tool_name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
        tool_arguments={
            "dataset_version_id": str(arguments_version_id or dataset_version_id),
        },
    )


def _result() -> AltAbnormalityResult:
    return AltAbnormalityResult(
        method_version="alt-gt-3x-uln/1.0",
        threshold_multiplier=Decimal(3),
        alt_row_count=1,
        eligible_row_count=1,
        excluded_row_count=0,
        subjects_with_exceedance=0,
        exceedances=(),
        findings=(),
    )


def test_confirmation_locks_executes_and_persists_structured_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record()
    fake = _FakeSession(record)

    async def calculation(session: AsyncSession, dataset_version_id: UUID) -> AltAbnormalityResult:
        assert session is cast(AsyncSession, fake)
        assert dataset_version_id == record.dataset_version_id
        return _result()

    monkeypatch.setattr(
        "trialops.agent.execution.calculate_stored_alt_gt_3x_uln",
        calculation,
    )

    execution = asyncio.run(execute_confirmed_plan(cast(AsyncSession, fake), record.id))

    assert execution.plan_id == record.id
    assert execution.status is PlanStatus.EXECUTED
    assert execution.result.dataset_version_id == record.dataset_version_id
    assert record.status is PlanStatus.EXECUTED
    assert record.result == execution.result.model_dump(mode="json")
    assert record.executed_at is not None
    assert fake.commit_calls == 1
    assert fake.rollback_calls == 0
    assert str(fake.statements[0]).endswith("FOR UPDATE")


@pytest.mark.parametrize(
    ("record", "expected_code"),
    [
        (None, AgentExecutionErrorCode.PLAN_NOT_FOUND),
        (
            _record(status=PlanStatus.EXECUTED),
            AgentExecutionErrorCode.PLAN_NOT_CONFIRMABLE,
        ),
    ],
)
def test_confirmation_rejects_missing_or_completed_plan(
    record: AgentPlanRecord | None,
    expected_code: AgentExecutionErrorCode,
) -> None:
    fake = _FakeSession(record)
    plan_id = record.id if record is not None else uuid4()

    with pytest.raises(AgentExecutionError) as raised:
        asyncio.run(execute_confirmed_plan(cast(AsyncSession, fake), plan_id))

    assert raised.value.code is expected_code
    assert fake.rollback_calls == 1
    assert fake.commit_calls == 0


@pytest.mark.parametrize("invalid_kind", ["arguments", "version", "tool"])
def test_confirmation_rejects_tampered_stored_plan(invalid_kind: str) -> None:
    record = _record()
    if invalid_kind == "arguments":
        record.tool_arguments = {}
    elif invalid_kind == "version":
        record.tool_arguments = {"dataset_version_id": str(uuid4())}
    else:
        record.tool_name = cast(ApprovedToolName, "unapproved_tool")
    fake = _FakeSession(record)

    with pytest.raises(AgentExecutionError) as raised:
        asyncio.run(execute_confirmed_plan(cast(AsyncSession, fake), record.id))

    assert raised.value.code is AgentExecutionErrorCode.INVALID_STORED_PLAN
    assert fake.rollback_calls == 1
    assert fake.commit_calls == 0


def test_confirmation_rejects_plan_with_unavailable_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record()
    fake = _FakeSession(record)

    async def unavailable(_session: AsyncSession, _version_id: UUID) -> AltAbnormalityResult:
        raise DatasetVersionNotFoundError("missing")

    monkeypatch.setattr(
        "trialops.agent.execution.calculate_stored_alt_gt_3x_uln",
        unavailable,
    )

    with pytest.raises(AgentExecutionError) as raised:
        asyncio.run(execute_confirmed_plan(cast(AsyncSession, fake), record.id))

    assert raised.value.code is AgentExecutionErrorCode.INVALID_STORED_PLAN
    assert raised.value.__cause__ is not None
    assert fake.rollback_calls == 1


def test_confirmation_rolls_back_result_storage_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record()
    conflict = IntegrityError("update", {}, Exception("conflict"))
    fake = _FakeSession(record, commit_error=conflict)

    async def calculation(_session: AsyncSession, _version_id: UUID) -> AltAbnormalityResult:
        return _result()

    monkeypatch.setattr(
        "trialops.agent.execution.calculate_stored_alt_gt_3x_uln",
        calculation,
    )

    with pytest.raises(AgentExecutionError) as raised:
        asyncio.run(execute_confirmed_plan(cast(AsyncSession, fake), record.id))

    assert raised.value.code is AgentExecutionErrorCode.DATABASE_CONFLICT
    assert raised.value.__cause__ is conflict
    assert fake.commit_calls == 1
    assert fake.rollback_calls == 1
