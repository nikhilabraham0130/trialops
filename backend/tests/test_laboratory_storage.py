"""Tests for transactional storage of versioned laboratory results."""

import asyncio
from collections.abc import Sequence
from decimal import Decimal
from types import TracebackType
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trialops.datasets.laboratory_results import LaboratoryResult, NormalRangeIndicator
from trialops.datasets.laboratory_storage import (
    LaboratoryStorageError,
    LaboratoryStorageErrorCode,
    LaboratoryStorageResult,
    store_laboratory_results,
)


class _FakeScalarResult:
    def __init__(self, values: Sequence[str]) -> None:
        self.values = tuple(values)

    def all(self) -> tuple[str, ...]:
        return self.values


class _FakeSession:
    def __init__(self, scalar_results: Sequence[object | None], subject_ids: Sequence[str]) -> None:
        self.scalar_results = list(scalar_results)
        self.subject_ids = tuple(subject_ids)
        self.inserted_batches: list[list[dict[str, object]]] = []
        self.execute_error_at: int | None = None

    async def scalar(self, _statement: object) -> object | None:
        return self.scalar_results.pop(0)

    async def scalars(self, _statement: object) -> _FakeScalarResult:
        return _FakeScalarResult(self.subject_ids)

    async def execute(self, _statement: object, records: list[dict[str, object]]) -> None:
        self.inserted_batches.append(records)
        if self.execute_error_at == len(self.inserted_batches):
            raise IntegrityError("insert", {}, Exception("constraint violation"))


class _FakeTransaction:
    def __init__(self, owner: "_FakeSessionFactory") -> None:
        self.owner = owner

    async def __aenter__(self) -> _FakeSession:
        self.owner.entered = True
        return self.owner.session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool:
        self.owner.exited = True
        self.owner.rolled_back = exc_type is not None
        if exc_type is None and self.owner.commit_error is not None:
            raise self.owner.commit_error
        return False


class _FakeSessionFactory:
    def __init__(
        self,
        scalar_results: Sequence[object | None] = (),
        *,
        subject_ids: Sequence[str] = ("TEST-001",),
        commit_error: IntegrityError | None = None,
    ) -> None:
        self.session = _FakeSession(scalar_results, subject_ids)
        self.commit_error = commit_error
        self.entered = False
        self.exited = False
        self.rolled_back = False
        self.begin_calls = 0

    def begin(self) -> _FakeTransaction:
        self.begin_calls += 1
        return _FakeTransaction(self)


def _results() -> tuple[LaboratoryResult, ...]:
    return (
        LaboratoryResult(
            source_record_number=1,
            study_id="TEST-STUDY",
            unique_subject_id="TEST-001",
            result_sequence=1,
            test_code="ALT",
            test_name="Alanine Aminotransferase",
            standard_result=Decimal("0"),
            standard_unit="U/L",
            lower_reference_limit=Decimal("0"),
            upper_reference_limit=Decimal("35"),
            range_indicator=NormalRangeIndicator.NORMAL,
            baseline_flag="Y",
            observed_at_text="2026-09-01T10:00",
        ),
        LaboratoryResult(
            source_record_number=2,
            study_id="TEST-STUDY",
            unique_subject_id="TEST-001",
            result_sequence=2,
            test_code="ALT",
            test_name="Alanine Aminotransferase",
            standard_result=None,
            standard_unit=None,
            lower_reference_limit=None,
            upper_reference_limit=None,
            range_indicator=None,
            baseline_flag=None,
            observed_at_text="2026-09-02T10:00",
        ),
    )


def _store(
    factory: _FakeSessionFactory,
    *,
    dataset_version_id: UUID | None = None,
    results: Sequence[LaboratoryResult] | None = None,
) -> LaboratoryStorageResult:
    session_factory = cast(async_sessionmaker[AsyncSession], factory)
    return asyncio.run(
        store_laboratory_results(
            session_factory,
            dataset_version_id=dataset_version_id or uuid4(),
            results=_results() if results is None else results,
        )
    )


def test_storage_commits_versioned_results_and_preserves_zero_and_null() -> None:
    dataset_version_id = uuid4()
    factory = _FakeSessionFactory(["TEST-STUDY", uuid4(), None])

    outcome = _store(factory, dataset_version_id=dataset_version_id)

    assert factory.begin_calls == 1
    assert factory.entered and factory.exited and not factory.rolled_back
    assert outcome == LaboratoryStorageResult(dataset_version_id, 2)
    assert len(factory.session.inserted_batches) == 1
    first, second = factory.session.inserted_batches[0]
    assert first["dataset_version_id"] == second["dataset_version_id"] == dataset_version_id
    assert first["standard_result"] == Decimal("0")
    assert second["standard_result"] is None
    assert first["range_indicator"] is NormalRangeIndicator.NORMAL
    assert second["baseline_flag"] is None
    assert first["id"] != second["id"]


def test_storage_splits_large_batch_without_starting_another_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("trialops.datasets.laboratory_storage.BATCH_SIZE", 1)
    factory = _FakeSessionFactory(["TEST-STUDY", uuid4(), None])

    outcome = _store(factory)

    assert outcome.result_count == 2
    assert factory.begin_calls == 1
    assert [len(batch) for batch in factory.session.inserted_batches] == [1, 1]


def test_storage_rejects_empty_batch_before_transaction() -> None:
    factory = _FakeSessionFactory()
    with pytest.raises(LaboratoryStorageError) as raised:
        _store(factory, results=())
    assert raised.value.code is LaboratoryStorageErrorCode.EMPTY_RESULT_SET
    assert factory.begin_calls == 0


def test_storage_rejects_duplicate_subject_sequence() -> None:
    results = _results()
    duplicate = results[1].model_copy(update={"result_sequence": 1})
    with pytest.raises(LaboratoryStorageError) as raised:
        _store(_FakeSessionFactory(), results=(results[0], duplicate))
    assert raised.value.code is LaboratoryStorageErrorCode.DUPLICATE_RESULT


def test_storage_rejects_duplicate_source_row() -> None:
    results = _results()
    duplicate = results[1].model_copy(update={"source_record_number": 1})
    with pytest.raises(LaboratoryStorageError) as raised:
        _store(_FakeSessionFactory(), results=(results[0], duplicate))
    assert raised.value.code is LaboratoryStorageErrorCode.DUPLICATE_SOURCE_RECORD


@pytest.mark.parametrize(
    ("scalar_results", "expected_code"),
    [
        ([None], LaboratoryStorageErrorCode.DATASET_VERSION_NOT_FOUND),
        (["OTHER-STUDY"], LaboratoryStorageErrorCode.STUDY_MISMATCH),
        (["TEST-STUDY", None], LaboratoryStorageErrorCode.LB_ARTIFACT_MISSING),
        (["TEST-STUDY", uuid4(), uuid4()], LaboratoryStorageErrorCode.RESULTS_ALREADY_STORED),
    ],
)
def test_storage_rejects_invalid_version_state(
    scalar_results: Sequence[object | None], expected_code: LaboratoryStorageErrorCode
) -> None:
    factory = _FakeSessionFactory(scalar_results)
    with pytest.raises(LaboratoryStorageError) as raised:
        _store(factory)
    assert raised.value.code is expected_code
    assert factory.rolled_back
    assert factory.session.inserted_batches == []


def test_storage_rejects_subject_missing_from_this_dm_version() -> None:
    factory = _FakeSessionFactory(["TEST-STUDY", uuid4(), None], subject_ids=("OTHER",))
    with pytest.raises(LaboratoryStorageError) as raised:
        _store(factory)
    assert raised.value.code is LaboratoryStorageErrorCode.SUBJECT_NOT_IN_VERSION
    assert factory.rolled_back


def test_storage_rolls_back_when_later_batch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("trialops.datasets.laboratory_storage.BATCH_SIZE", 1)
    factory = _FakeSessionFactory(["TEST-STUDY", uuid4(), None])
    factory.session.execute_error_at = 2
    with pytest.raises(LaboratoryStorageError) as raised:
        _store(factory)
    assert raised.value.code is LaboratoryStorageErrorCode.DATABASE_CONFLICT
    assert factory.rolled_back
    assert len(factory.session.inserted_batches) == 2


def test_storage_translates_commit_conflict() -> None:
    conflict = IntegrityError("insert", {}, Exception("foreign-key violation"))
    factory = _FakeSessionFactory(["TEST-STUDY", uuid4(), None], commit_error=conflict)
    with pytest.raises(LaboratoryStorageError) as raised:
        _store(factory)
    assert raised.value.code is LaboratoryStorageErrorCode.DATABASE_CONFLICT
    assert raised.value.__cause__ is conflict
