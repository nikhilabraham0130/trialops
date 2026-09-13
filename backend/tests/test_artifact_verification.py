"""Tests for source-artifact integrity verification."""

from datetime import date
from pathlib import Path

import pytest

from trialops.datasets.manifest import (
    ArtifactKind,
    SourceArtifact,
    SourceIdentity,
    SourceManifest,
)
from trialops.datasets.verification import (
    ArtifactVerificationError,
    VerificationErrorCode,
    VerifiedArtifact,
    verify_source_package,
)

SOURCE_BYTES = b"abc"
SOURCE_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_source_package_verifies_matching_artifact(tmp_path: Path) -> None:
    """A file matching its size and SHA-256 fingerprint is trusted."""
    artifact_path = tmp_path / "dm.json"
    artifact_path.write_bytes(SOURCE_BYTES)

    verified = verify_source_package(tmp_path, _manifest())

    assert verified == (
        VerifiedArtifact(
            filename="dm.json",
            path=artifact_path,
            byte_size=len(SOURCE_BYTES),
            sha256=SOURCE_SHA256,
        ),
    )


def test_source_package_rejects_missing_directory(tmp_path: Path) -> None:
    """Verification fails before ingestion when the source directory is absent."""
    missing_directory = tmp_path / "missing"

    with pytest.raises(ArtifactVerificationError) as raised:
        verify_source_package(missing_directory, _manifest())

    assert raised.value.code is VerificationErrorCode.SOURCE_DIRECTORY_UNAVAILABLE
    assert raised.value.filename is None


def test_source_package_rejects_file_as_directory(tmp_path: Path) -> None:
    """The source package location must point to a directory."""
    source_file = tmp_path / "source"
    source_file.write_bytes(SOURCE_BYTES)

    with pytest.raises(ArtifactVerificationError) as raised:
        verify_source_package(source_file, _manifest())

    assert raised.value.code is VerificationErrorCode.SOURCE_DIRECTORY_UNAVAILABLE


def test_source_package_rejects_missing_artifact(tmp_path: Path) -> None:
    """Every artifact declared by the manifest is required."""
    with pytest.raises(ArtifactVerificationError) as raised:
        verify_source_package(tmp_path, _manifest())

    assert raised.value.code is VerificationErrorCode.ARTIFACT_MISSING
    assert raised.value.filename == "dm.json"


def test_source_package_rejects_directory_as_artifact(tmp_path: Path) -> None:
    """A directory cannot masquerade as a declared source file."""
    (tmp_path / "dm.json").mkdir()

    with pytest.raises(ArtifactVerificationError) as raised:
        verify_source_package(tmp_path, _manifest())

    assert raised.value.code is VerificationErrorCode.ARTIFACT_NOT_FILE


def test_source_package_rejects_size_mismatch(tmp_path: Path) -> None:
    """A changed byte count blocks the source package."""
    (tmp_path / "dm.json").write_bytes(b"abcd")

    with pytest.raises(ArtifactVerificationError) as raised:
        verify_source_package(tmp_path, _manifest())

    assert raised.value.code is VerificationErrorCode.SIZE_MISMATCH


def test_source_package_rejects_checksum_mismatch(tmp_path: Path) -> None:
    """Same-sized but changed content is detected by its fingerprint."""
    (tmp_path / "dm.json").write_bytes(b"abd")

    with pytest.raises(ArtifactVerificationError) as raised:
        verify_source_package(tmp_path, _manifest())

    assert raised.value.code is VerificationErrorCode.CHECKSUM_MISMATCH


def test_source_package_reports_unreadable_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operating-system read failures receive a stable error code."""
    artifact_path = tmp_path / "dm.json"
    artifact_path.write_bytes(SOURCE_BYTES)

    def deny_open(_path: Path, _mode: str) -> None:
        raise PermissionError

    monkeypatch.setattr(Path, "open", deny_open)

    with pytest.raises(ArtifactVerificationError) as raised:
        verify_source_package(tmp_path, _manifest())

    assert raised.value.code is VerificationErrorCode.ARTIFACT_UNREADABLE


def _manifest() -> SourceManifest:
    """Build a TrialOps-owned manifest for independent test bytes."""
    source = SourceIdentity.model_validate(
        {
            "name": "TrialOps test source",
            "repository_url": "https://example.com/trialops/test-source",
            "revision": "a" * 40,
            "retrieved_on": date(2026, 9, 12),
            "attribution": "TrialOps-owned test fixture",
        }
    )
    artifact = SourceArtifact(
        filename="dm.json",
        kind=ArtifactKind.DATASET_JSON,
        domain="DM",
        byte_size=len(SOURCE_BYTES),
        sha256=SOURCE_SHA256,
    )
    return SourceManifest(
        manifest_version="1.0",
        source=source,
        study_id="TEST-STUDY",
        dataset_json_version="1.1.0",
        artifacts=(artifact,),
    )
