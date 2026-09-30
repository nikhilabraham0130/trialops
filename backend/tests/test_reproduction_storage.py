"""Recorded reproduction history must match the unchanged saved analysis."""

import asyncio
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from test_reproduction import _plan

from trialops.agent.contracts import AnalysisPlanDetails
from trialops.lineage.models import ReproductionRunRecord
from trialops.lineage.reproduction import ReproductionComparison, compare_structured_results
from trialops.lineage.storage import (
    ReproductionStorageError,
    ReproductionStorageErrorCode,
    list_reproduction_runs,
    store_reproduction_run,
)


class Rows:
    def __init__(self, records: list[ReproductionRunRecord]) -> None:
        self.records = records

    def all(self) -> list[ReproductionRunRecord]:
        return self.records


class Session:
    def __init__(self, records: list[ReproductionRunRecord] | None = None) -> None:
        self.records = records or []
        self.added: ReproductionRunRecord | None = None
        self.commits = 0
        self.rollbacks = 0

    async def scalar(self, _query: object) -> object:
        return object()

    async def scalars(self, _query: object) -> Rows:
        return Rows(self.records)

    def add(self, record: ReproductionRunRecord) -> None:
        self.added = record

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _comparison(plan: AnalysisPlanDetails) -> ReproductionComparison:
    assert plan.result is not None
    return compare_structured_results(
        plan_id=plan.id,
        dataset_version_id=plan.dataset_version_id,
        tool_name=plan.tool_call.name,
        stored=plan.result,
        reproduced=plan.result,
    )


def test_storage_appends_comparison_when_saved_result_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    monkeypatch.setattr("trialops.lineage.storage.validate_analysis_plan_record", lambda _: plan)
    session = Session()

    stored = asyncio.run(store_reproduction_run(cast(AsyncSession, session), _comparison(plan)))

    assert stored.status == "EXACT_MATCH"
    assert session.added is not None
    assert stored.id == session.added.id
    assert session.commits == 1
    assert session.rollbacks == 0


def test_storage_rejects_a_changed_result_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan()
    monkeypatch.setattr("trialops.lineage.storage.validate_analysis_plan_record", lambda _: plan)
    session = Session()
    changed = _comparison(plan).model_copy(update={"stored_result_sha256": "b" * 64})

    with pytest.raises(ReproductionStorageError) as raised:
        asyncio.run(store_reproduction_run(cast(AsyncSession, session), changed))

    assert raised.value.code is ReproductionStorageErrorCode.PLAN_CHANGED
    assert session.added is None
    assert session.rollbacks == 1


def test_history_returns_saved_comparison_without_rerunning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    comparison = _comparison(plan)
    record = ReproductionRunRecord(
        id=uuid4(),
        plan_id=plan.id,
        status="EXACT_MATCH",
        stored_result_sha256=comparison.stored_result_sha256,
        reproduced_result_sha256=comparison.reproduced_result_sha256,
        difference_count=0,
        differences=[],
        differences_truncated=False,
        created_at=datetime.now(UTC),
    )

    async def fake_plan(_session: AsyncSession, _plan_id: object) -> AnalysisPlanDetails:
        return plan

    monkeypatch.setattr("trialops.lineage.storage.get_analysis_plan", fake_plan)
    history = asyncio.run(list_reproduction_runs(cast(AsyncSession, Session([record])), plan.id))
    assert len(history) == 1
    assert history[0].id == record.id
    assert history[0].status == "EXACT_MATCH"
