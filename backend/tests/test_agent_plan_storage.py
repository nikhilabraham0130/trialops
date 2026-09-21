"""Tests for persistent, server-controlled agent plans."""

import asyncio
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.contracts import (
    AnalysisPlan,
    ApprovedToolName,
    ModelPlanProposal,
    PlanStatus,
    create_analysis_plan,
)
from trialops.agent.models import AgentPlanRecord
from trialops.agent.storage import (
    AgentPlanStorageError,
    AgentPlanStorageErrorCode,
    store_analysis_plan,
)


class _FakeSession:
    def __init__(self, commit_error: IntegrityError | None = None) -> None:
        self.added: object | None = None
        self.commit_error = commit_error
        self.commit_calls = 0
        self.rollback_calls = 0

    def add(self, instance: object) -> None:
        self.added = instance

    async def commit(self) -> None:
        self.commit_calls += 1
        if self.commit_error is not None:
            raise self.commit_error

    async def rollback(self) -> None:
        self.rollback_calls += 1


def _plan() -> tuple[AnalysisPlan, UUID]:
    dataset_version_id = uuid4()
    plan = create_analysis_plan(
        question="Were any ALT measurements above three times the upper limit?",
        dataset_version_id=dataset_version_id,
        proposal=ModelPlanProposal(
            tool_name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
            purpose="Use the approved ALT threshold calculation.",
        ),
    )
    return plan, dataset_version_id


def test_storage_commits_exact_plan_fields_and_trusted_arguments() -> None:
    plan, dataset_version_id = _plan()
    fake = _FakeSession()

    asyncio.run(store_analysis_plan(cast(AsyncSession, fake), plan))

    assert fake.commit_calls == 1
    assert fake.rollback_calls == 0
    record = cast(AgentPlanRecord, fake.added)
    assert record.id == plan.id
    assert record.dataset_version_id == dataset_version_id
    assert record.question == plan.question
    assert record.purpose == plan.purpose
    assert record.status is PlanStatus.AWAITING_CONFIRMATION
    assert record.tool_name is ApprovedToolName.CALCULATE_ALT_GT_3X_ULN
    assert record.tool_arguments == {"dataset_version_id": str(dataset_version_id)}


def test_storage_rolls_back_and_translates_database_conflict() -> None:
    plan, _ = _plan()
    conflict = IntegrityError("insert", {}, Exception("duplicate plan id"))
    fake = _FakeSession(commit_error=conflict)

    with pytest.raises(AgentPlanStorageError) as raised:
        asyncio.run(store_analysis_plan(cast(AsyncSession, fake), plan))

    assert raised.value.code is AgentPlanStorageErrorCode.DATABASE_CONFLICT
    assert str(raised.value) == "The analysis plan could not be stored safely."
    assert raised.value.__cause__ is conflict
    assert fake.commit_calls == 1
    assert fake.rollback_calls == 1
