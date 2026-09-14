"""Tests for transactional storage of normalized DM subjects."""

import asyncio
from collections.abc import Sequence
from types import TracebackType
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trialops.datasets.demographics import DemographicsSubject
from trialops.datasets.demographics_storage import (
    DemographicsStorageError,
    DemographicsStorageErrorCode,
    DemographicsStorageResult,
    store_demographics_subjects,
)
from trialops.datasets.models import DMSubject


class _FakeSession:
    """Return configured query results and record inserted objects."""

    def __init__(self, scalar_results: Sequence[object | None]) -> None:
        self.scalar_results = list(scalar_results)
        self.added: tuple[object, ...] = ()

    async def scalar(self, _statement: object) -> object | None:
        return self.scalar_results.pop(0)

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
    """Provide one observable transaction for a storage test."""

    def __init__(
        self,
        scalar_results: Sequence[object | None] = (),
        *,
        commit_error: IntegrityError | None = None,
    ) -> None:
        self.session = _FakeSession(scalar_results)
        self.commit_error = commit_error
        self.entered = False
        self.exited = False
        self.begin_calls = 0

    def begin(self) -> _FakeTransaction:
        self.begin_calls += 1
        return _FakeTransaction(self)


def test_storage_inserts_every_normalized_subject_in_one_transaction() -> None:
    """A complete valid batch becomes dataset-versioned DM rows."""
    dataset_version_id = uuid4()
    factory = _FakeSessionFactory(["TEST-STUDY", uuid4(), None])

    result = _store(factory, dataset_version_id=dataset_version_id)

    assert factory.begin_calls == 1
    assert factory.entered is True
    assert factory.exited is True
    assert result.dataset_version_id == dataset_version_id
    assert result.subject_count == 2

    records = cast(tuple[DMSubject, ...], factory.session.added)
    assert len(records) == 2
    assert {record.unique_subject_id for record in records} == {"TEST-001", "TEST-002"}
    assert {record.dataset_version_id for record in records} == {dataset_version_id}
    assert records[0].source_record_number == 1
    assert records[0].age == 34
    assert records[0].actual_arm == "Placebo"
    assert result.subject_ids == tuple(record.id for record in records)


def test_storage_rejects_an_empty_subject_set_before_opening_transaction() -> None:
    """An empty DM import cannot masquerade as successful storage."""
    factory = _FakeSessionFactory()

    with pytest.raises(DemographicsStorageError) as raised:
        _store(factory, subjects=())

    assert raised.value.code is DemographicsStorageErrorCode.EMPTY_SUBJECT_SET
    assert factory.begin_calls == 0


def test_storage_rejects_duplicate_subject_identity() -> None:
    """One DM batch cannot contain the same USUBJID more than once."""
    subjects = _subjects()
    duplicate = subjects[1].model_copy(update={"unique_subject_id": subjects[0].unique_subject_id})

    with pytest.raises(DemographicsStorageError) as raised:
        _store(_FakeSessionFactory(), subjects=(subjects[0], duplicate))

    assert raised.value.code is DemographicsStorageErrorCode.DUPLICATE_SUBJECT


def test_storage_rejects_duplicate_source_record_number() -> None:
    """One source row position cannot identify two normalized records."""
    subjects = _subjects()
    duplicate = subjects[1].model_copy(
        update={"source_record_number": subjects[0].source_record_number}
    )

    with pytest.raises(DemographicsStorageError) as raised:
        _store(_FakeSessionFactory(), subjects=(subjects[0], duplicate))

    assert raised.value.code is DemographicsStorageErrorCode.DUPLICATE_SOURCE_RECORD


def test_storage_rejects_unknown_dataset_version() -> None:
    """Subjects cannot be stored without a registered parent version."""
    factory = _FakeSessionFactory([None])

    with pytest.raises(DemographicsStorageError) as raised:
        _store(factory)

    assert raised.value.code is DemographicsStorageErrorCode.DATASET_VERSION_NOT_FOUND
    assert factory.exited is True


def test_storage_rejects_subjects_from_another_study() -> None:
    """Source STUDYID must agree with the catalog's owning study."""
    factory = _FakeSessionFactory(["DIFFERENT-STUDY"])

    with pytest.raises(DemographicsStorageError) as raised:
        _store(factory)

    assert raised.value.code is DemographicsStorageErrorCode.STUDY_MISMATCH


def test_storage_requires_verified_dm_provenance() -> None:
    """A dataset version without a DM artifact cannot receive DM records."""
    factory = _FakeSessionFactory(["TEST-STUDY", None])

    with pytest.raises(DemographicsStorageError) as raised:
        _store(factory)

    assert raised.value.code is DemographicsStorageErrorCode.DM_ARTIFACT_MISSING


def test_storage_rejects_repeated_import_for_one_version() -> None:
    """A dataset version's immutable DM snapshot is stored only once."""
    factory = _FakeSessionFactory(["TEST-STUDY", uuid4(), uuid4()])

    with pytest.raises(DemographicsStorageError) as raised:
        _store(factory)

    assert raised.value.code is DemographicsStorageErrorCode.SUBJECTS_ALREADY_STORED


def test_storage_translates_concurrent_database_conflict() -> None:
    """A commit conflict becomes a stable error after automatic rollback."""
    conflict = IntegrityError("insert", {}, Exception("unique violation"))
    factory = _FakeSessionFactory(["TEST-STUDY", uuid4(), None], commit_error=conflict)

    with pytest.raises(DemographicsStorageError) as raised:
        _store(factory)

    assert raised.value.code is DemographicsStorageErrorCode.DATABASE_CONFLICT
    assert raised.value.__cause__ is conflict


def _store(
    factory: _FakeSessionFactory,
    *,
    dataset_version_id: UUID | None = None,
    subjects: Sequence[DemographicsSubject] | None = None,
) -> DemographicsStorageResult:
    """Run storage through the production boundary using a database fake."""
    session_factory = cast(async_sessionmaker[AsyncSession], factory)
    return asyncio.run(
        store_demographics_subjects(
            session_factory,
            dataset_version_id=dataset_version_id or uuid4(),
            subjects=_subjects() if subjects is None else subjects,
        )
    )


def _subjects() -> tuple[DemographicsSubject, ...]:
    """Create two independently validated normalized subjects."""
    return (
        DemographicsSubject(
            source_record_number=1,
            study_id="TEST-STUDY",
            unique_subject_id="TEST-001",
            subject_id="001",
            age=34,
            age_unit="YEARS",
            sex="F",
            race="WHITE",
            planned_arm="Placebo",
            actual_arm="Placebo",
        ),
        DemographicsSubject(
            source_record_number=2,
            study_id="TEST-STUDY",
            unique_subject_id="TEST-002",
            subject_id="002",
            age=52,
            age_unit="YEARS",
            sex="M",
            race="ASIAN",
            planned_arm="Treatment",
            actual_arm="Treatment",
        ),
    )
