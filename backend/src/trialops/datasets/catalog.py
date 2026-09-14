"""Transactional registration of verified source packages."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trialops.datasets.manifest import SourceArtifact, SourceManifest
from trialops.datasets.models import DatasetVersion, SourceArtifactRecord
from trialops.datasets.verification import VerifiedArtifact
from trialops.studies.models import Study


class DatasetCatalogErrorCode(StrEnum):
    """Stable reasons that a verified package cannot be registered."""

    INVALID_VERSION_LABEL = "INVALID_VERSION_LABEL"
    VERIFIED_ARTIFACT_MISMATCH = "VERIFIED_ARTIFACT_MISMATCH"
    VERSION_LABEL_EXISTS = "VERSION_LABEL_EXISTS"
    DATASET_CONTENT_EXISTS = "DATASET_CONTENT_EXISTS"
    DATABASE_CONFLICT = "DATABASE_CONFLICT"


class DatasetCatalogError(ValueError):
    """Raised when catalog registration cannot complete safely."""

    def __init__(self, code: DatasetCatalogErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class DatasetRegistration:
    """Identifiers created by one successful catalog transaction."""

    study_id: UUID
    dataset_version_id: UUID
    source_artifact_ids: tuple[UUID, ...]
    combined_checksum: str


def calculate_package_checksum(artifacts: Sequence[SourceArtifact]) -> str:
    """Create an order-independent fingerprint for one complete file set."""
    canonical_artifacts = [
        {
            "byte_size": artifact.byte_size,
            "domain": artifact.domain,
            "filename": artifact.filename,
            "kind": artifact.kind.value,
            "sha256": artifact.sha256,
        }
        for artifact in sorted(artifacts, key=lambda item: item.filename.casefold())
    ]
    canonical_json = json.dumps(
        canonical_artifacts,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(canonical_json).hexdigest()


async def register_verified_dataset(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    manifest: SourceManifest,
    verified_artifacts: Sequence[VerifiedArtifact],
    version_label: str,
) -> DatasetRegistration:
    """Register one verified source package in a single database transaction."""
    normalized_label = _normalize_version_label(version_label)
    verified_by_filename = _match_verified_artifacts(manifest, verified_artifacts)
    combined_checksum = calculate_package_checksum(manifest.artifacts)

    try:
        async with session_factory.begin() as session:
            study = await session.scalar(select(Study).where(Study.study_oid == manifest.study_id))
            if study is None:
                study = Study(id=uuid4(), study_oid=manifest.study_id)
                session.add(study)

            label_owner = await session.scalar(
                select(DatasetVersion.id).where(
                    DatasetVersion.study_id == study.id,
                    DatasetVersion.version_label == normalized_label,
                )
            )
            if label_owner is not None:
                raise DatasetCatalogError(
                    DatasetCatalogErrorCode.VERSION_LABEL_EXISTS,
                    f"Dataset version label already exists for study: {normalized_label}",
                )

            content_owner = await session.scalar(
                select(DatasetVersion.id).where(
                    DatasetVersion.study_id == study.id,
                    DatasetVersion.combined_checksum == combined_checksum,
                )
            )
            if content_owner is not None:
                raise DatasetCatalogError(
                    DatasetCatalogErrorCode.DATASET_CONTENT_EXISTS,
                    "The same source package is already registered for this study.",
                )

            dataset_version = DatasetVersion(
                id=uuid4(),
                study_id=study.id,
                version_label=normalized_label,
                source_manifest=manifest.model_dump(mode="json"),
                combined_checksum=combined_checksum,
            )
            session.add(dataset_version)

            artifact_records = tuple(
                SourceArtifactRecord(
                    id=uuid4(),
                    dataset_version_id=dataset_version.id,
                    filename=artifact.filename,
                    kind=artifact.kind,
                    domain=artifact.domain,
                    byte_size=verified_by_filename[artifact.filename].byte_size,
                    sha256=verified_by_filename[artifact.filename].sha256,
                )
                for artifact in manifest.artifacts
            )
            session.add_all(artifact_records)

            registration = DatasetRegistration(
                study_id=study.id,
                dataset_version_id=dataset_version.id,
                source_artifact_ids=tuple(record.id for record in artifact_records),
                combined_checksum=combined_checksum,
            )
    except IntegrityError as exc:
        raise DatasetCatalogError(
            DatasetCatalogErrorCode.DATABASE_CONFLICT,
            "The dataset catalog changed during registration; no records were saved.",
        ) from exc

    return registration


def _normalize_version_label(version_label: str) -> str:
    """Reject labels that cannot be stored as useful catalog identifiers."""
    normalized_label = version_label.strip()
    if not normalized_label or len(normalized_label) > 100:
        raise DatasetCatalogError(
            DatasetCatalogErrorCode.INVALID_VERSION_LABEL,
            "Dataset version label must contain between 1 and 100 characters.",
        )
    return normalized_label


def _match_verified_artifacts(
    manifest: SourceManifest,
    verified_artifacts: Sequence[VerifiedArtifact],
) -> dict[str, VerifiedArtifact]:
    """Require verification evidence for exactly the manifest's artifacts."""
    verified_by_filename = {artifact.filename: artifact for artifact in verified_artifacts}
    expected_by_filename = {artifact.filename: artifact for artifact in manifest.artifacts}

    if len(verified_by_filename) != len(verified_artifacts) or set(verified_by_filename) != set(
        expected_by_filename
    ):
        raise DatasetCatalogError(
            DatasetCatalogErrorCode.VERIFIED_ARTIFACT_MISMATCH,
            "Verified artifacts do not match the source manifest.",
        )

    for filename, expected in expected_by_filename.items():
        observed = verified_by_filename[filename]
        if observed.byte_size != expected.byte_size or observed.sha256 != expected.sha256:
            raise DatasetCatalogError(
                DatasetCatalogErrorCode.VERIFIED_ARTIFACT_MISMATCH,
                f"Verified artifact identity does not match the manifest: {filename}",
            )

    return verified_by_filename
