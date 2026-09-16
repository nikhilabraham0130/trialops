"""Read-only study queries for API presentation."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.datasets.models import DatasetVersion, DatasetVersionStatus, DMSubject
from trialops.studies.models import Study


@dataclass(frozen=True, slots=True)
class DatasetVersionSubjectCount:
    """One dataset version and its normalized DM population size."""

    id: UUID
    version_label: str
    status: DatasetVersionStatus
    subject_count: int


@dataclass(frozen=True, slots=True)
class StudySummary:
    """One study with every registered dataset-version subject count."""

    id: UUID
    study_oid: str
    title: str | None
    dataset_versions: tuple[DatasetVersionSubjectCount, ...]


async def list_study_summaries(session: AsyncSession) -> tuple[StudySummary, ...]:
    """Return studies and deterministic DM counts ordered for display."""
    studies = tuple((await session.scalars(select(Study).order_by(Study.study_oid))).all())
    summaries: list[StudySummary] = []

    for study in studies:
        dataset_versions = tuple(
            (
                await session.scalars(
                    select(DatasetVersion)
                    .where(DatasetVersion.study_id == study.id)
                    .order_by(DatasetVersion.created_at, DatasetVersion.id)
                )
            ).all()
        )
        version_summaries: list[DatasetVersionSubjectCount] = []
        for dataset_version in dataset_versions:
            subject_count = await session.scalar(
                select(func.count(DMSubject.id)).where(
                    DMSubject.dataset_version_id == dataset_version.id
                )
            )
            version_summaries.append(
                DatasetVersionSubjectCount(
                    id=dataset_version.id,
                    version_label=dataset_version.version_label,
                    status=dataset_version.status,
                    subject_count=subject_count or 0,
                )
            )

        summaries.append(
            StudySummary(
                id=study.id,
                study_oid=study.study_oid,
                title=study.title,
                dataset_versions=tuple(version_summaries),
            )
        )

    return tuple(summaries)
