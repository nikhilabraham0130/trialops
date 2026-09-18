"""Tests for transactional storage of versioned adverse events."""

import asyncio
from collections.abc import Sequence
from types import TracebackType
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trialops.datasets.adverse_event_storage import (
    AdverseEventStorageError,
    AdverseEventStorageErrorCode,
    AdverseEventStorageResult,
    store_adverse_events,
)
from trialops.datasets.adverse_events import AdverseEvent, AdverseEventSeverity
from trialops.datasets.models import AEEvent


class _FakeScalarResult:
    def __init__(self, values: Sequence[str]) -> None:
        self.values = tuple(values)

    def all(self) -> tuple[str, ...]:
        return self.values


class _FakeSession:
    """Return configured query results and record inserted objects."""

    def __init__(self, scalar_results: Sequence[object | None], subject_ids: Sequence[str]) -> None:
        self.scalar_results = list(scalar_results)
        self.subject_ids = tuple(subject_ids)
        self.added: tuple[object, ...] = ()

    async def scalar(self, _statement: object) -> object | None:
        return self.scalar_results.pop(0)

    async def scalars(self, _statement: object) -> _FakeScalarResult:
        return _FakeScalarResult(self.subject_ids)

    def add_all(self, instances: Sequence[object]) -> None:
        self.added = tuple(instances)


class _FakeTransaction:
    """Model sessionmaker's commit-or-rollback context manager."""

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
        self.begin_calls = 0

    def begin(self) -> _FakeTransaction:
        self.begin_calls += 1
        return _FakeTransaction(self)


def _events() -> tuple[AdverseEvent, ...]:
    return (
        AdverseEvent(
            source_record_number=1,
            study_id="TEST-STUDY",
            unique_subject_id="TEST-001",
            event_sequence=1,
            reported_term="Headache",
            preferred_term="HEADACHE",
            severity=AdverseEventSeverity.MILD,
            serious_flag="N",
            start_date_text="2026-09-01",
            end_date_text="2026-09-02",
        ),
        AdverseEvent(
            source_record_number=2,
            study_id="TEST-STUDY",
            unique_subject_id="TEST-001",
            event_sequence=2,
            reported_term="Nausea",
            preferred_term="NAUSEA",
            severity=AdverseEventSeverity.SEVERE,
            serious_flag="Y",
            start_date_text="2026-09-03",
            end_date_text=None,
        ),
    )


def _store(
    factory: _FakeSessionFactory,
    *,
    dataset_version_id: UUID | None = None,
    events: Sequence[AdverseEvent] | None = None,
) -> AdverseEventStorageResult:
    session_factory = cast(async_sessionmaker[AsyncSession], factory)
    return asyncio.run(
        store_adverse_events(
            session_factory,
            dataset_version_id=dataset_version_id or uuid4(),
            events=_events() if events is None else events,
        )
    )


def test_storage_commits_versioned_events_in_one_transaction() -> None:
    dataset_version_id = uuid4()
    factory = _FakeSessionFactory(["TEST-STUDY", uuid4(), None])

    result = _store(factory, dataset_version_id=dataset_version_id)

    assert factory.begin_calls == 1
    assert factory.entered and factory.exited
    assert result.dataset_version_id == dataset_version_id
    assert result.event_count == 2

    records = cast(tuple[AEEvent, ...], factory.session.added)
    assert len(records) == 2
    assert {record.dataset_version_id for record in records} == {dataset_version_id}
    assert {record.unique_subject_id for record in records} == {"TEST-001"}
    assert records[0].source_record_number == 1
    assert records[0].severity is AdverseEventSeverity.MILD
    assert records[1].event_sequence == 2
    assert records[1].serious_flag == "Y"
    assert records[1].end_date_text is None
    assert result.event_ids == tuple(record.id for record in records)


def test_storage_rejects_empty_event_batch_before_transaction() -> None:
    factory = _FakeSessionFactory()

    with pytest.raises(AdverseEventStorageError) as raised:
        _store(factory, events=())

    assert raised.value.code is AdverseEventStorageErrorCode.EMPTY_EVENT_SET
    assert factory.begin_calls == 0


def test_storage_rejects_duplicate_event_key() -> None:
    events = _events()
    duplicate = events[1].model_copy(update={"event_sequence": 1})

    with pytest.raises(AdverseEventStorageError) as raised:
        _store(_FakeSessionFactory(), events=(events[0], duplicate))

    assert raised.value.code is AdverseEventStorageErrorCode.DUPLICATE_EVENT


def test_storage_rejects_duplicate_source_row() -> None:
    events = _events()
    duplicate = events[1].model_copy(update={"source_record_number": 1})

    with pytest.raises(AdverseEventStorageError) as raised:
        _store(_FakeSessionFactory(), events=(events[0], duplicate))

    assert raised.value.code is AdverseEventStorageErrorCode.DUPLICATE_SOURCE_RECORD


@pytest.mark.parametrize(
    ("scalar_results", "expected_code"),
    [
        ([None], AdverseEventStorageErrorCode.DATASET_VERSION_NOT_FOUND),
        (["OTHER-STUDY"], AdverseEventStorageErrorCode.STUDY_MISMATCH),
        (["TEST-STUDY", None], AdverseEventStorageErrorCode.AE_ARTIFACT_MISSING),
        (["TEST-STUDY", uuid4(), uuid4()], AdverseEventStorageErrorCode.EVENTS_ALREADY_STORED),
    ],
)
def test_storage_rejects_invalid_version_state(
    scalar_results: Sequence[object | None], expected_code: AdverseEventStorageErrorCode
) -> None:
    factory = _FakeSessionFactory(scalar_results)

    with pytest.raises(AdverseEventStorageError) as raised:
        _store(factory)

    assert raised.value.code is expected_code
    assert factory.exited
    assert factory.session.added == ()


def test_storage_rejects_ae_subject_missing_from_this_dm_version() -> None:
    factory = _FakeSessionFactory(["TEST-STUDY", uuid4(), None], subject_ids=("OTHER-SUBJECT",))

    with pytest.raises(AdverseEventStorageError) as raised:
        _store(factory)

    assert raised.value.code is AdverseEventStorageErrorCode.SUBJECT_NOT_IN_VERSION
    assert factory.session.added == ()


def test_storage_translates_concurrent_database_conflict() -> None:
    conflict = IntegrityError("insert", {}, Exception("foreign-key violation"))
    factory = _FakeSessionFactory(["TEST-STUDY", uuid4(), None], commit_error=conflict)

    with pytest.raises(AdverseEventStorageError) as raised:
        _store(factory)

    assert raised.value.code is AdverseEventStorageErrorCode.DATABASE_CONFLICT
    assert raised.value.__cause__ is conflict
