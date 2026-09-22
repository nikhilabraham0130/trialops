"""Tests for validated retrieval of persisted agent plans."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.contracts import ApprovedToolName, PlanStatus
from trialops.agent.models import AgentPlanRecord
from trialops.agent.queries import (
    AgentPlanQueryError,
    AgentPlanQueryErrorCode,
    get_analysis_plan,
)
from trialops.analytics.contracts import AltAbnormalityResponse


class _FakeSession:
    def __init__(self, record: AgentPlanRecord | None) -> None:
        self.record = record
        self.statements: list[object] = []

    async def scalar(self, statement: object) -> AgentPlanRecord | None:
        self.statements.append(statement)
        return self.record


def _result(dataset_version_id: UUID) -> dict[str, object]:
    result = AltAbnormalityResponse(
        dataset_version_id=dataset_version_id,
        method_version="alt-gt-3x-uln/1.0",
        threshold_multiplier=Decimal(3),
        alt_row_count=1,
        eligible_row_count=1,
        excluded_row_count=0,
        qualifying_measurement_count=0,
        subjects_with_qualifying_measurement=0,
        exceedances=(),
        findings=(),
        timing_limitation="A blank baseline flag does not prove post-treatment timing.",
    )
    return result.model_dump(mode="json")


def _record(status: PlanStatus = PlanStatus.AWAITING_CONFIRMATION) -> AgentPlanRecord:
    dataset_version_id = uuid4()
    return AgentPlanRecord(
        id=uuid4(),
        dataset_version_id=dataset_version_id,
        question="Were any ALT results above three times the upper limit?",
        purpose="Use the approved deterministic ALT calculation.",
        status=status,
        tool_name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
        tool_arguments={"dataset_version_id": str(dataset_version_id)},
        result=_result(dataset_version_id) if status is PlanStatus.EXECUTED else None,
        created_at=datetime(2026, 9, 22, 12, tzinfo=UTC),
        executed_at=(
            datetime(2026, 9, 22, 12, 1, tzinfo=UTC) if status is PlanStatus.EXECUTED else None
        ),
    )


@pytest.mark.parametrize(
    ("status", "expects_result", "confirmation_required"),
    [
        (PlanStatus.AWAITING_CONFIRMATION, False, True),
        (PlanStatus.EXECUTED, True, False),
    ],
)
def test_query_rebuilds_typed_plan_state(
    status: PlanStatus,
    expects_result: bool,
    confirmation_required: bool,
) -> None:
    record = _record(status)
    fake = _FakeSession(record)

    details = asyncio.run(get_analysis_plan(cast(AsyncSession, fake), record.id))

    assert details.id == record.id
    assert details.dataset_version_id == record.dataset_version_id
    assert details.status is status
    assert details.confirmation_required is confirmation_required
    assert (details.result is not None) is expects_result
    assert details.tool_call.arguments.dataset_version_id == record.dataset_version_id
    assert len(fake.statements) == 1


def test_query_reports_missing_plan() -> None:
    fake = _FakeSession(None)

    with pytest.raises(AgentPlanQueryError) as raised:
        asyncio.run(get_analysis_plan(cast(AsyncSession, fake), uuid4()))

    assert raised.value.code is AgentPlanQueryErrorCode.PLAN_NOT_FOUND


@pytest.mark.parametrize("invalid_kind", ["arguments", "version", "tool"])
def test_query_rejects_invalid_tool_invocation(invalid_kind: str) -> None:
    record = _record()
    if invalid_kind == "arguments":
        record.tool_arguments = {}
    elif invalid_kind == "version":
        record.tool_arguments = {"dataset_version_id": str(uuid4())}
    else:
        record.tool_name = cast(ApprovedToolName, "unapproved_tool")

    with pytest.raises(AgentPlanQueryError) as raised:
        asyncio.run(get_analysis_plan(cast(AsyncSession, _FakeSession(record)), record.id))

    assert raised.value.code is AgentPlanQueryErrorCode.INVALID_STORED_PLAN


def test_query_rejects_invalid_result_structure() -> None:
    record = _record(PlanStatus.EXECUTED)
    record.result = {"unexpected": "shape"}

    with pytest.raises(AgentPlanQueryError) as raised:
        asyncio.run(get_analysis_plan(cast(AsyncSession, _FakeSession(record)), record.id))

    assert raised.value.code is AgentPlanQueryErrorCode.INVALID_STORED_PLAN
    assert raised.value.__cause__ is not None


def test_query_rejects_result_from_different_dataset() -> None:
    record = _record(PlanStatus.EXECUTED)
    record.result = _result(uuid4())

    with pytest.raises(AgentPlanQueryError) as raised:
        asyncio.run(get_analysis_plan(cast(AsyncSession, _FakeSession(record)), record.id))

    assert raised.value.code is AgentPlanQueryErrorCode.INVALID_STORED_PLAN


@pytest.mark.parametrize("missing_kind", ["result", "executed_at"])
def test_query_rejects_incomplete_executed_plan(missing_kind: str) -> None:
    record = _record(PlanStatus.EXECUTED)
    if missing_kind == "result":
        record.result = None
    else:
        record.executed_at = None

    with pytest.raises(AgentPlanQueryError) as raised:
        asyncio.run(get_analysis_plan(cast(AsyncSession, _FakeSession(record)), record.id))

    assert raised.value.code is AgentPlanQueryErrorCode.INVALID_STORED_PLAN


@pytest.mark.parametrize("unexpected_kind", ["result", "executed_at"])
def test_query_rejects_output_on_unexecuted_plan(unexpected_kind: str) -> None:
    record = _record()
    if unexpected_kind == "result":
        record.result = _result(record.dataset_version_id)
    else:
        record.executed_at = datetime.now(UTC)

    with pytest.raises(AgentPlanQueryError) as raised:
        asyncio.run(get_analysis_plan(cast(AsyncSession, _FakeSession(record)), record.id))

    assert raised.value.code is AgentPlanQueryErrorCode.INVALID_STORED_PLAN


def test_query_rejects_invalid_core_plan_fields() -> None:
    record = _record()
    record.question = " "

    with pytest.raises(AgentPlanQueryError) as raised:
        asyncio.run(get_analysis_plan(cast(AsyncSession, _FakeSession(record)), record.id))

    assert raised.value.code is AgentPlanQueryErrorCode.INVALID_STORED_PLAN
    assert raised.value.__cause__ is not None
