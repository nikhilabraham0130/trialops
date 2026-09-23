"""Tests for storing verified interpretations against unchanged executed plans."""

import asyncio
from copy import copy
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.contracts import ApprovedToolName, PlanStatus
from trialops.agent.fake_interpretation_model import FakeInterpretationModel
from trialops.agent.interpretation_contracts import (
    GroundingStatus,
    NumericClaim,
    NumericFactName,
    StoredInterpretation,
)
from trialops.agent.interpretation_model import InterpretationModelError
from trialops.agent.interpretation_workflow import (
    InterpretationWorkflowError,
    InterpretationWorkflowErrorCode,
    create_verified_plan_interpretation,
)
from trialops.agent.models import AgentPlanRecord
from trialops.analytics.contracts import AltAbnormalityResponse

VALID_RESPONSE = (
    '{"summary":"There were 4 qualifying measurements above 3 times ULN.",'
    '"numeric_claims":['
    '{"field":"qualifying_measurement_count","value":4},'
    '{"field":"threshold_multiplier","value":3}]}'
)


class _FakeSession:
    def __init__(
        self,
        records: list[AgentPlanRecord | None],
        *,
        commit_error: IntegrityError | None = None,
    ) -> None:
        self.records = records
        self.commit_error = commit_error
        self.statements: list[object] = []
        self.rollback_calls = 0
        self.commit_calls = 0

    async def scalar(self, statement: object) -> AgentPlanRecord | None:
        self.statements.append(statement)
        return self.records.pop(0)

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1
        if self.commit_error is not None:
            raise self.commit_error


def _result(dataset_version_id: UUID) -> dict[str, object]:
    return AltAbnormalityResponse(
        dataset_version_id=dataset_version_id,
        method_version="alt-gt-3x-uln/1.0",
        threshold_multiplier=Decimal(3),
        alt_row_count=10,
        eligible_row_count=10,
        excluded_row_count=0,
        qualifying_measurement_count=4,
        subjects_with_qualifying_measurement=2,
        exceedances=(),
        findings=(),
        timing_limitation="Timing is limited by the source baseline flag.",
    ).model_dump(mode="json")


def _record(status: PlanStatus = PlanStatus.EXECUTED) -> AgentPlanRecord:
    version_id = uuid4()
    return AgentPlanRecord(
        id=uuid4(),
        dataset_version_id=version_id,
        question="Were any ALT measurements elevated?",
        purpose="Explain the approved ALT calculation.",
        status=status,
        tool_name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
        tool_arguments={"dataset_version_id": str(version_id)},
        result=_result(version_id) if status is PlanStatus.EXECUTED else None,
        interpretation=None,
        created_at=datetime(2026, 9, 23, 12, tzinfo=UTC),
        executed_at=(
            datetime(2026, 9, 23, 12, 1, tzinfo=UTC) if status is PlanStatus.EXECUTED else None
        ),
    )


def _stored_interpretation() -> dict[str, object]:
    return StoredInterpretation(
        summary="There were 4 qualifying measurements above 3 times ULN.",
        numeric_claims=(
            NumericClaim(
                field=NumericFactName.QUALIFYING_MEASUREMENT_COUNT,
                value=Decimal(4),
            ),
            NumericClaim(
                field=NumericFactName.THRESHOLD_MULTIPLIER,
                value=Decimal(3),
            ),
        ),
        grounding_status=GroundingStatus.NUMERICALLY_VERIFIED,
        prompt_version="alt-result-interpretation/1.0",
        model_id="fake-model-v1",
        generated_at=datetime(2026, 9, 23, 12, 2, tzinfo=UTC),
    ).model_dump(mode="json")


def test_workflow_generates_without_lock_then_persists_after_relocking() -> None:
    record = _record()
    fake = _FakeSession([record, record])
    model = FakeInterpretationModel(VALID_RESPONSE, model_id="fake-model-v1")

    stored = asyncio.run(
        create_verified_plan_interpretation(cast(AsyncSession, fake), model, record.id)
    )

    assert stored.grounding_status is GroundingStatus.NUMERICALLY_VERIFIED
    assert stored.model_id == "fake-model-v1"
    assert record.interpretation == stored.model_dump(mode="json")
    assert fake.rollback_calls == 1
    assert fake.commit_calls == 1
    assert len(fake.statements) == 2
    assert not str(fake.statements[0]).endswith("FOR UPDATE")
    assert str(fake.statements[1]).endswith("FOR UPDATE")
    assert len(model.requests) == 1


def test_workflow_translates_missing_plan() -> None:
    fake = _FakeSession([None])

    with pytest.raises(InterpretationWorkflowError) as raised:
        asyncio.run(
            create_verified_plan_interpretation(
                cast(AsyncSession, fake), FakeInterpretationModel(VALID_RESPONSE), uuid4()
            )
        )

    assert raised.value.code is InterpretationWorkflowErrorCode.PLAN_NOT_FOUND
    assert fake.rollback_calls == 1


def test_workflow_requires_executed_plan_before_calling_model() -> None:
    record = _record(PlanStatus.AWAITING_CONFIRMATION)
    fake = _FakeSession([record])
    model = FakeInterpretationModel(VALID_RESPONSE)

    with pytest.raises(InterpretationWorkflowError) as raised:
        asyncio.run(create_verified_plan_interpretation(cast(AsyncSession, fake), model, record.id))

    assert raised.value.code is InterpretationWorkflowErrorCode.PLAN_NOT_EXECUTED
    assert model.requests == []
    assert fake.rollback_calls == 1


def test_workflow_rejects_existing_interpretation_before_calling_model() -> None:
    record = _record()
    record.interpretation = _stored_interpretation()
    fake = _FakeSession([record])
    model = FakeInterpretationModel(VALID_RESPONSE)

    with pytest.raises(InterpretationWorkflowError) as raised:
        asyncio.run(create_verified_plan_interpretation(cast(AsyncSession, fake), model, record.id))

    assert raised.value.code is InterpretationWorkflowErrorCode.INTERPRETATION_EXISTS
    assert model.requests == []


@pytest.mark.parametrize(
    ("model", "expected_code"),
    [
        (
            FakeInterpretationModel(
                VALID_RESPONSE,
                error=InterpretationModelError("provider detail"),
            ),
            InterpretationWorkflowErrorCode.MODEL_UNAVAILABLE,
        ),
        (
            FakeInterpretationModel("not json"),
            InterpretationWorkflowErrorCode.INVALID_MODEL_RESPONSE,
        ),
        (
            FakeInterpretationModel(
                '{"summary":"There were 14 measurements.",'
                '"numeric_claims":['
                '{"field":"qualifying_measurement_count","value":14}]}'
            ),
            InterpretationWorkflowErrorCode.UNGROUNDED_NUMERIC_CLAIM,
        ),
    ],
)
def test_workflow_translates_model_and_grounding_failures(
    model: FakeInterpretationModel,
    expected_code: InterpretationWorkflowErrorCode,
) -> None:
    record = _record()
    fake = _FakeSession([record])

    with pytest.raises(InterpretationWorkflowError) as raised:
        asyncio.run(create_verified_plan_interpretation(cast(AsyncSession, fake), model, record.id))

    assert raised.value.code is expected_code
    assert record.interpretation is None
    assert fake.commit_calls == 0


def test_workflow_rejects_plan_deleted_during_generation() -> None:
    record = _record()
    fake = _FakeSession([record, None])

    with pytest.raises(InterpretationWorkflowError) as raised:
        asyncio.run(
            create_verified_plan_interpretation(
                cast(AsyncSession, fake), FakeInterpretationModel(VALID_RESPONSE), record.id
            )
        )

    assert raised.value.code is InterpretationWorkflowErrorCode.PLAN_NOT_FOUND
    assert fake.rollback_calls == 2


def test_workflow_rejects_concurrent_interpretation() -> None:
    original = _record()
    current = copy(original)
    current.interpretation = _stored_interpretation()
    fake = _FakeSession([original, current])

    with pytest.raises(InterpretationWorkflowError) as raised:
        asyncio.run(
            create_verified_plan_interpretation(
                cast(AsyncSession, fake), FakeInterpretationModel(VALID_RESPONSE), original.id
            )
        )

    assert raised.value.code is InterpretationWorkflowErrorCode.INTERPRETATION_EXISTS
    assert fake.rollback_calls == 2


def test_workflow_rejects_plan_changed_during_generation() -> None:
    original = _record()
    current = copy(original)
    current.purpose = "A changed purpose."
    fake = _FakeSession([original, current])

    with pytest.raises(InterpretationWorkflowError) as raised:
        asyncio.run(
            create_verified_plan_interpretation(
                cast(AsyncSession, fake), FakeInterpretationModel(VALID_RESPONSE), original.id
            )
        )

    assert raised.value.code is InterpretationWorkflowErrorCode.PLAN_CHANGED
    assert fake.rollback_calls == 2


def test_workflow_translates_invalid_state_after_relocking() -> None:
    original = _record()
    current = copy(original)
    current.result = {"invalid": "result"}
    fake = _FakeSession([original, current])

    with pytest.raises(InterpretationWorkflowError) as raised:
        asyncio.run(
            create_verified_plan_interpretation(
                cast(AsyncSession, fake), FakeInterpretationModel(VALID_RESPONSE), original.id
            )
        )

    assert raised.value.code is InterpretationWorkflowErrorCode.INVALID_STORED_PLAN
    assert fake.rollback_calls == 2


def test_workflow_rolls_back_storage_conflict() -> None:
    record = _record()
    conflict = IntegrityError("update", {}, Exception("conflict"))
    fake = _FakeSession([record, record], commit_error=conflict)

    with pytest.raises(InterpretationWorkflowError) as raised:
        asyncio.run(
            create_verified_plan_interpretation(
                cast(AsyncSession, fake), FakeInterpretationModel(VALID_RESPONSE), record.id
            )
        )

    assert raised.value.code is InterpretationWorkflowErrorCode.DATABASE_CONFLICT
    assert raised.value.__cause__ is conflict
    assert fake.commit_calls == 1
    assert fake.rollback_calls == 2
