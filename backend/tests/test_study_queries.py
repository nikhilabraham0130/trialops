"""Tests for read-only study summary queries."""

import asyncio
from collections.abc import Sequence
from typing import cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from trialops.datasets.models import DatasetVersion, DatasetVersionStatus
from trialops.studies.models import Study
from trialops.studies.queries import list_study_summaries


class _FakeScalarCollection:
    """Expose configured ORM objects through SQLAlchemy's all() shape."""

    def __init__(self, values: Sequence[object]) -> None:
        self.values = list(values)

    def all(self) -> list[object]:
        return self.values


class _FakeSession:
    """Return ordered collection and scalar results for query tests."""

    def __init__(
        self,
        collections: Sequence[Sequence[object]],
        counts: Sequence[int | None],
    ) -> None:
        self.collections = list(collections)
        self.counts = list(counts)

    async def scalars(self, _statement: object) -> _FakeScalarCollection:
        return _FakeScalarCollection(self.collections.pop(0))

    async def scalar(self, _statement: object) -> int | None:
        return self.counts.pop(0)


def test_study_summaries_include_each_version_and_subject_count() -> None:
    """Studies are returned with ordered dataset-version population counts."""
    first_study = Study(id=uuid4(), study_oid="STUDY-A", title="First study")
    second_study = Study(id=uuid4(), study_oid="STUDY-B")
    first_version = DatasetVersion(
        id=uuid4(),
        study_id=first_study.id,
        version_label="initial",
        status=DatasetVersionStatus.VALID,
        source_manifest={},
        combined_checksum="a" * 64,
    )
    second_version = DatasetVersion(
        id=uuid4(),
        study_id=first_study.id,
        version_label="corrected",
        status=DatasetVersionStatus.RECEIVED,
        source_manifest={},
        combined_checksum="b" * 64,
    )
    fake = _FakeSession(
        collections=[
            [first_study, second_study],
            [first_version, second_version],
            [],
        ],
        counts=[306, None],
    )

    summaries = asyncio.run(list_study_summaries(cast(AsyncSession, fake)))

    assert len(summaries) == 2
    assert summaries[0].study_oid == "STUDY-A"
    assert summaries[0].title == "First study"
    assert [version.version_label for version in summaries[0].dataset_versions] == [
        "initial",
        "corrected",
    ]
    assert [version.subject_count for version in summaries[0].dataset_versions] == [306, 0]
    assert summaries[1].study_oid == "STUDY-B"
    assert summaries[1].dataset_versions == ()


def test_study_summaries_return_an_empty_catalog() -> None:
    """An empty database produces an empty response rather than an error."""
    fake = _FakeSession(collections=[[]], counts=[])

    summaries = asyncio.run(list_study_summaries(cast(AsyncSession, fake)))

    assert summaries == ()
