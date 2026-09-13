"""Integrity verification for external clinical-data artifacts."""

from dataclasses import dataclass
from enum import StrEnum
from hashlib import file_digest
from os import fstat
from pathlib import Path

from trialops.datasets.manifest import SourceArtifact, SourceManifest


class VerificationErrorCode(StrEnum):
    """Stable reasons that a source package cannot be trusted."""

    SOURCE_DIRECTORY_UNAVAILABLE = "SOURCE_DIRECTORY_UNAVAILABLE"
    ARTIFACT_MISSING = "ARTIFACT_MISSING"
    ARTIFACT_NOT_FILE = "ARTIFACT_NOT_FILE"
    ARTIFACT_UNREADABLE = "ARTIFACT_UNREADABLE"
    SIZE_MISMATCH = "SIZE_MISMATCH"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"


class ArtifactVerificationError(ValueError):
    """Raised when a source package differs from its approved manifest."""

    def __init__(
        self,
        code: VerificationErrorCode,
        message: str,
        *,
        filename: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.filename = filename


@dataclass(frozen=True, slots=True)
class VerifiedArtifact:
    """Observed identity of one artifact that matched its manifest."""

    filename: str
    path: Path
    byte_size: int
    sha256: str


def verify_source_package(
    source_directory: Path,
    manifest: SourceManifest,
) -> tuple[VerifiedArtifact, ...]:
    """Verify every artifact declared by a source manifest."""
    try:
        source_root = source_directory.resolve(strict=True)
    except OSError as exc:
        raise ArtifactVerificationError(
            VerificationErrorCode.SOURCE_DIRECTORY_UNAVAILABLE,
            "Source directory is unavailable.",
        ) from exc

    if not source_root.is_dir():
        raise ArtifactVerificationError(
            VerificationErrorCode.SOURCE_DIRECTORY_UNAVAILABLE,
            "Source path is not a directory.",
        )

    return tuple(_verify_artifact(source_root, artifact) for artifact in manifest.artifacts)


def _verify_artifact(source_root: Path, artifact: SourceArtifact) -> VerifiedArtifact:
    """Compare one source artifact with its expected identity."""
    artifact_path = source_root / artifact.filename
    if not artifact_path.exists():
        raise ArtifactVerificationError(
            VerificationErrorCode.ARTIFACT_MISSING,
            f"Required source artifact is missing: {artifact.filename}",
            filename=artifact.filename,
        )
    if not artifact_path.is_file():
        raise ArtifactVerificationError(
            VerificationErrorCode.ARTIFACT_NOT_FILE,
            f"Source artifact is not a regular file: {artifact.filename}",
            filename=artifact.filename,
        )

    try:
        with artifact_path.open("rb") as source_file:
            actual_size = fstat(source_file.fileno()).st_size
            if actual_size != artifact.byte_size:
                raise ArtifactVerificationError(
                    VerificationErrorCode.SIZE_MISMATCH,
                    f"Source artifact size does not match its manifest: {artifact.filename}",
                    filename=artifact.filename,
                )
            actual_sha256 = file_digest(source_file, "sha256").hexdigest()
    except OSError as exc:
        raise ArtifactVerificationError(
            VerificationErrorCode.ARTIFACT_UNREADABLE,
            f"Source artifact cannot be read: {artifact.filename}",
            filename=artifact.filename,
        ) from exc

    if actual_sha256 != artifact.sha256:
        raise ArtifactVerificationError(
            VerificationErrorCode.CHECKSUM_MISMATCH,
            f"Source artifact checksum does not match its manifest: {artifact.filename}",
            filename=artifact.filename,
        )

    return VerifiedArtifact(
        filename=artifact.filename,
        path=artifact_path,
        byte_size=actual_size,
        sha256=actual_sha256,
    )
