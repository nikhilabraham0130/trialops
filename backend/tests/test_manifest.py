"""Tests for clinical-data source manifests."""

import json
from pathlib import Path
from typing import NotRequired, TypedDict

import pytest

from trialops.datasets.manifest import ArtifactKind, ManifestLoadError, load_source_manifest

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "data" / "manifests" / "cdisc-pilot.json"


class SourceIdentityPayload(TypedDict):
    """JSON-compatible source identity used by test manifests."""

    name: str
    repository_url: str
    revision: str
    retrieved_on: str
    attribution: str


class ArtifactPayload(TypedDict):
    """JSON-compatible artifact identity used by test manifests."""

    filename: str
    kind: str
    byte_size: int
    sha256: str
    domain: NotRequired[str]


class ManifestPayload(TypedDict):
    """Complete JSON-compatible test manifest."""

    manifest_version: str
    source: SourceIdentityPayload
    study_id: str
    dataset_json_version: str
    artifacts: list[ArtifactPayload]


def test_cdisc_pilot_manifest_loads_expected_source() -> None:
    """The committed CDISC manifest identifies the assessed source package."""
    manifest = load_source_manifest(MANIFEST_PATH)

    assert manifest.manifest_version == "1.0"
    assert manifest.study_id == "CDISCPILOT01"
    assert manifest.dataset_json_version == "1.1.0"
    assert manifest.source.revision == "667511d4b183871d74392ba691c935c38d431d39"
    assert {artifact.filename for artifact in manifest.artifacts} == {
        "ae.json",
        "define.xml",
        "dm.json",
        "lb.json",
    }
    assert {
        artifact.domain
        for artifact in manifest.artifacts
        if artifact.kind is ArtifactKind.DATASET_JSON
    } == {"AE", "DM", "LB"}


def test_manifest_rejects_invalid_checksum(tmp_path: Path) -> None:
    """A checksum must be exactly one lowercase SHA-256 digest."""
    invalid_manifest = _minimal_manifest()
    invalid_manifest["artifacts"][0]["sha256"] = "not-a-sha256"
    path = _write_manifest(tmp_path, invalid_manifest)

    with pytest.raises(ManifestLoadError, match="Invalid source manifest"):
        load_source_manifest(path)


def test_manifest_rejects_duplicate_domain(tmp_path: Path) -> None:
    """One manifest cannot ambiguously define a domain more than once."""
    invalid_manifest = _minimal_manifest()
    invalid_manifest["artifacts"].append(
        {
            "filename": "dm-copy.json",
            "kind": "dataset-json",
            "domain": "DM",
            "byte_size": 20,
            "sha256": "b" * 64,
        }
    )
    path = _write_manifest(tmp_path, invalid_manifest)

    with pytest.raises(ManifestLoadError, match="Invalid source manifest"):
        load_source_manifest(path)


def test_manifest_rejects_duplicate_filename(tmp_path: Path) -> None:
    """Artifact filenames remain unique regardless of letter casing."""
    invalid_manifest = _minimal_manifest()
    invalid_manifest["artifacts"].append(
        {
            "filename": "DM.JSON",
            "kind": "dataset-json",
            "domain": "AE",
            "byte_size": 20,
            "sha256": "b" * 64,
        }
    )
    path = _write_manifest(tmp_path, invalid_manifest)

    with pytest.raises(ManifestLoadError, match="Invalid source manifest"):
        load_source_manifest(path)


def test_manifest_rejects_dataset_without_domain(tmp_path: Path) -> None:
    """A Dataset-JSON artifact must identify the clinical domain it contains."""
    invalid_manifest = _minimal_manifest()
    del invalid_manifest["artifacts"][0]["domain"]
    path = _write_manifest(tmp_path, invalid_manifest)

    with pytest.raises(ManifestLoadError, match="Invalid source manifest"):
        load_source_manifest(path)


def test_manifest_rejects_domain_on_define_xml(tmp_path: Path) -> None:
    """Study metadata must not be mislabeled as a clinical data domain."""
    invalid_manifest = _minimal_manifest()
    invalid_manifest["artifacts"][0]["kind"] = "define-xml"
    path = _write_manifest(tmp_path, invalid_manifest)

    with pytest.raises(ManifestLoadError, match="Invalid source manifest"):
        load_source_manifest(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("study_id", "s" * 129),
        ("filename", "f" * 256),
    ],
)
def test_manifest_rejects_values_too_large_for_catalog_columns(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    """Validated manifest values always fit their PostgreSQL columns."""
    invalid_manifest = _minimal_manifest()
    if field == "study_id":
        invalid_manifest["study_id"] = value
    else:
        invalid_manifest["artifacts"][0]["filename"] = value
    path = _write_manifest(tmp_path, invalid_manifest)

    with pytest.raises(ManifestLoadError, match="Invalid source manifest"):
        load_source_manifest(path)


def test_manifest_reports_missing_file(tmp_path: Path) -> None:
    """A missing manifest produces a stable application-specific error."""
    missing_path = tmp_path / "missing.json"

    with pytest.raises(ManifestLoadError, match="Unable to read source manifest"):
        load_source_manifest(missing_path)


def _minimal_manifest() -> ManifestPayload:
    """Create independent test data without modifying CDISC source records."""
    return {
        "manifest_version": "1.0",
        "source": {
            "name": "TrialOps test source",
            "repository_url": "https://example.com/trialops/test-source",
            "revision": "a" * 40,
            "retrieved_on": "2026-09-12",
            "attribution": "TrialOps-owned test fixture",
        },
        "study_id": "TEST-STUDY",
        "dataset_json_version": "1.1.0",
        "artifacts": [
            {
                "filename": "dm.json",
                "kind": "dataset-json",
                "domain": "DM",
                "byte_size": 10,
                "sha256": "a" * 64,
            }
        ],
    }


def _write_manifest(tmp_path: Path, manifest: ManifestPayload) -> Path:
    """Write a temporary manifest used only by one test."""
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path
