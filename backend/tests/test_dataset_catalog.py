"""Tests for transactional dataset catalog registration."""

import asyncio
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from types import TracebackType
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trialops.datasets.catalog import (
    DatasetCatalogError,
    DatasetCatalogErrorCode,
    DatasetRegistration,
    calculate_package_checksum,
    register_verified_dataset,
)
from trialops.datasets.manifest import (
    ArtifactKind,
    SourceArtifact,
    SourceIdentity,
    SourceManifest,
)
from trialops.datasets.models import DatasetVersion, SourceArtifactRecord
from trialops.datasets.verification import VerifiedArtifact
from trialops.studies.models import Study


class _FakeSession:
    """Record database operations without opening a real connection."""

    def __init__(self, scalar_results: Sequence[object | None]) -> None:
        self.scalar_results = list(scalar_results)
        self.added: list[object] = []
        self.added_batches: list[tuple[object, ...]] = []

    async def scalar(self, _statement: object) -> object | None:
        return self.scalar_results.pop(0)

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def add_all(self, instances: Sequence[object]) -> None:
        batch = tuple(instances)
        self.added_batches.append(batch)
        self.added.extend(batch)


class _FakeTransaction:
    """Provide the asynchronous context used by sessionmaker.begin()."""

    def __init__(
        self,
        owner: "_FakeSessionFactory",
        session: _FakeSession,
    ) -> None:
        self.owner = owner
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        self.owner.entered = True
        return self.session

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
    """Create exactly one observable fake transaction."""

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
        return _FakeTransaction(self, self.session)


def test_package_checksum_is_stable_when_manifest_order_changes() -> None:
    """Reordering identical files does not create a different package identity."""
    manifest = _manifest()

    forward = calculate_package_checksum(manifest.artifacts)
    reversed_order = calculate_package_checksum(tuple(reversed(manifest.artifacts)))

    assert forward == reversed_order
    assert len(forward) == 64


def test_package_checksum_changes_when_artifact_identity_changes() -> None:
    """A changed source file produces a different package fingerprint."""
    manifest = _manifest()
    changed = manifest.artifacts[0].model_copy(update={"sha256": "c" * 64})

    assert calculate_package_checksum((changed, manifest.artifacts[1])) != (
        calculate_package_checksum(manifest.artifacts)
    )


def test_registration_creates_study_version_and_artifacts_together() -> None:
    """A new study package becomes one connected set of catalog records."""
    manifest = _manifest()
    factory = _FakeSessionFactory([None, None, None])

    registration = _register(factory, manifest=manifest, version_label="  pilot-v1  ")

    assert factory.begin_calls == 1
    assert factory.entered is True
    assert factory.exited is True
    assert registration.combined_checksum == calculate_package_checksum(manifest.artifacts)

    study = factory.session.added[0]
    dataset_version = factory.session.added[1]
    artifact_records = cast(
        tuple[SourceArtifactRecord, ...],
        factory.session.added_batches[0],
    )

    assert isinstance(study, Study)
    assert study.study_oid == "TEST-STUDY"
    assert registration.study_id == study.id

    assert isinstance(dataset_version, DatasetVersion)
    assert dataset_version.study_id == study.id
    assert dataset_version.version_label == "pilot-v1"
    assert dataset_version.source_manifest["source"]["retrieved_on"] == "2026-09-12"
    assert registration.dataset_version_id == dataset_version.id

    assert len(artifact_records) == 2
    assert all(isinstance(record, SourceArtifactRecord) for record in artifact_records)
    assert {record.filename for record in artifact_records} == {"dm.json", "define.xml"}
    assert {record.dataset_version_id for record in artifact_records} == {dataset_version.id}
    assert registration.source_artifact_ids == tuple(record.id for record in artifact_records)


def test_registration_reuses_an_existing_study() -> None:
    """A second data delivery remains attached to the original study row."""
    existing_study = Study(id=uuid4(), study_oid="TEST-STUDY")
    factory = _FakeSessionFactory([existing_study, None, None])

    registration = _register(factory)

    assert registration.study_id == existing_study.id
    assert all(not isinstance(item, Study) for item in factory.session.added)


@pytest.mark.parametrize("version_label", ["", "   ", "x" * 101])
def test_registration_rejects_invalid_version_labels(version_label: str) -> None:
    """Empty and oversized labels fail before a transaction starts."""
    factory = _FakeSessionFactory()

    with pytest.raises(DatasetCatalogError) as raised:
        _register(factory, version_label=version_label)

    assert raised.value.code is DatasetCatalogErrorCode.INVALID_VERSION_LABEL
    assert factory.begin_calls == 0


def test_registration_rejects_an_incomplete_verified_artifact_set() -> None:
    """Every manifest file needs matching verification evidence before storage."""
    factory = _FakeSessionFactory()

    with pytest.raises(DatasetCatalogError) as raised:
        _register(factory, verified_artifacts=_verified_artifacts()[:1])

    assert raised.value.code is DatasetCatalogErrorCode.VERIFIED_ARTIFACT_MISMATCH
    assert factory.begin_calls == 0


def test_registration_rejects_duplicate_verification_evidence() -> None:
    """Two verification results cannot ambiguously describe the same filename."""
    factory = _FakeSessionFactory()
    duplicate = (_verified_artifacts()[0], _verified_artifacts()[0])

    with pytest.raises(DatasetCatalogError) as raised:
        _register(factory, verified_artifacts=duplicate)

    assert raised.value.code is DatasetCatalogErrorCode.VERIFIED_ARTIFACT_MISMATCH


@pytest.mark.parametrize(
    "replacement",
    [
        VerifiedArtifact("dm.json", Path("dm.json"), 4, "a" * 64),
        VerifiedArtifact("dm.json", Path("dm.json"), 3, "c" * 64),
    ],
)
def test_registration_rejects_verification_identity_mismatch(
    replacement: VerifiedArtifact,
) -> None:
    """Observed sizes and hashes must still match the approved manifest."""
    factory = _FakeSessionFactory()
    verified = (replacement, _verified_artifacts()[1])

    with pytest.raises(DatasetCatalogError) as raised:
        _register(factory, verified_artifacts=verified)

    assert raised.value.code is DatasetCatalogErrorCode.VERIFIED_ARTIFACT_MISMATCH


def test_registration_rejects_a_reused_version_label() -> None:
    """One study cannot assign the same readable label to two snapshots."""
    factory = _FakeSessionFactory([Study(id=uuid4(), study_oid="TEST-STUDY"), uuid4()])

    with pytest.raises(DatasetCatalogError) as raised:
        _register(factory)

    assert raised.value.code is DatasetCatalogErrorCode.VERSION_LABEL_EXISTS
    assert factory.exited is True


def test_registration_rejects_already_registered_content() -> None:
    """Different labels cannot disguise an identical source package."""
    factory = _FakeSessionFactory([Study(id=uuid4(), study_oid="TEST-STUDY"), None, uuid4()])

    with pytest.raises(DatasetCatalogError) as raised:
        _register(factory)

    assert raised.value.code is DatasetCatalogErrorCode.DATASET_CONTENT_EXISTS


def test_registration_translates_a_concurrent_database_conflict() -> None:
    """A commit race becomes a stable domain error after automatic rollback."""
    conflict = IntegrityError("insert", {}, Exception("unique violation"))
    factory = _FakeSessionFactory([None, None, None], commit_error=conflict)

    with pytest.raises(DatasetCatalogError) as raised:
        _register(factory)

    assert raised.value.code is DatasetCatalogErrorCode.DATABASE_CONFLICT
    assert raised.value.__cause__ is conflict


def _register(
    factory: _FakeSessionFactory,
    *,
    manifest: SourceManifest | None = None,
    verified_artifacts: Sequence[VerifiedArtifact] | None = None,
    version_label: str = "pilot-v1",
) -> DatasetRegistration:
    """Run registration with typed production boundaries around a test fake."""
    session_factory = cast(async_sessionmaker[AsyncSession], factory)
    return asyncio.run(
        register_verified_dataset(
            session_factory,
            manifest=manifest or _manifest(),
            verified_artifacts=verified_artifacts or _verified_artifacts(),
            version_label=version_label,
        )
    )


def _manifest() -> SourceManifest:
    """Build a two-file manifest for catalog unit tests."""
    return SourceManifest(
        manifest_version="1.0",
        source=SourceIdentity.model_validate(
            {
                "name": "TrialOps test source",
                "repository_url": "https://example.com/trialops/source",
                "revision": "b" * 40,
                "retrieved_on": date(2026, 9, 12),
                "attribution": "TrialOps-owned test fixture",
            }
        ),
        study_id="TEST-STUDY",
        dataset_json_version="1.1.0",
        artifacts=(
            SourceArtifact(
                filename="dm.json",
                kind=ArtifactKind.DATASET_JSON,
                domain="DM",
                byte_size=3,
                sha256="a" * 64,
            ),
            SourceArtifact(
                filename="define.xml",
                kind=ArtifactKind.DEFINE_XML,
                byte_size=5,
                sha256="b" * 64,
            ),
        ),
    )


def _verified_artifacts() -> tuple[VerifiedArtifact, ...]:
    """Create verification evidence matching the catalog test manifest."""
    return (
        VerifiedArtifact("dm.json", Path("dm.json"), 3, "a" * 64),
        VerifiedArtifact("define.xml", Path("define.xml"), 5, "b" * 64),
    )
