"""Validated contracts for describing external clinical-data sources."""

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError, model_validator

Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
GitRevision = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
ArtifactFilename = Annotated[
    str,
    Field(min_length=1, max_length=255, pattern=r"^[^/\\]+$"),
]
DomainCode = Annotated[str, Field(pattern=r"^[A-Z]{2,8}$")]


class ManifestLoadError(ValueError):
    """Raised when a source manifest cannot be read or validated."""


class ArtifactKind(StrEnum):
    """Supported kinds of original source artifacts."""

    DATASET_JSON = "dataset-json"
    DEFINE_XML = "define-xml"


class SourceIdentity(BaseModel):
    """Identity and attribution of an upstream data source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    repository_url: AnyHttpUrl
    revision: GitRevision
    retrieved_on: date
    attribution: str = Field(min_length=1)


class SourceArtifact(BaseModel):
    """Expected identity of one original file in a source package."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: ArtifactFilename
    kind: ArtifactKind
    byte_size: int = Field(gt=0)
    sha256: Sha256Digest
    domain: DomainCode | None = None

    @model_validator(mode="after")
    def validate_domain_usage(self) -> Self:
        """Require domain codes only where they have a defined meaning."""
        if self.kind is ArtifactKind.DATASET_JSON and self.domain is None:
            raise ValueError("Dataset-JSON artifacts require a domain code.")
        if self.kind is ArtifactKind.DEFINE_XML and self.domain is not None:
            raise ValueError("Define-XML artifacts must not have a domain code.")
        return self


class SourceManifest(BaseModel):
    """Immutable provenance contract for one external study package."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_version: Literal["1.0"]
    source: SourceIdentity
    study_id: str = Field(min_length=1, max_length=128)
    dataset_json_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    artifacts: tuple[SourceArtifact, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_artifacts(self) -> Self:
        """Reject ambiguous duplicate filenames and domain files."""
        filenames = [artifact.filename.casefold() for artifact in self.artifacts]
        if len(filenames) != len(set(filenames)):
            raise ValueError("Artifact filenames must be unique.")

        domains = [
            artifact.domain
            for artifact in self.artifacts
            if artifact.kind is ArtifactKind.DATASET_JSON
        ]
        if len(domains) != len(set(domains)):
            raise ValueError("Dataset-JSON domain codes must be unique.")

        return self


def load_source_manifest(path: Path) -> SourceManifest:
    """Read and validate one source manifest from disk."""
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ManifestLoadError(f"Unable to read source manifest: {path.name}") from exc

    try:
        return SourceManifest.model_validate_json(payload)
    except ValidationError as exc:
        raise ManifestLoadError(f"Invalid source manifest: {path.name}") from exc
