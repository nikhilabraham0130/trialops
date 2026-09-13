"""Tests for foundational SQLAlchemy table models."""

from sqlalchemy import CheckConstraint, Enum, ForeignKeyConstraint, UniqueConstraint

from trialops.datasets.manifest import ArtifactKind
from trialops.datasets.models import DatasetVersionStatus
from trialops.db.models import Base


def _constraint_names(table_name: str, constraint_type: type[object]) -> set[str | None]:
    table = Base.metadata.tables[table_name]
    names: set[str | None] = set()
    for constraint in table.constraints:
        if isinstance(constraint, constraint_type):
            name = constraint.name
            names.add(None if name is None else str(name))
    return names


def test_metadata_registers_foundational_catalog_tables() -> None:
    """Alembic sees every table required for the dataset catalog."""
    assert set(Base.metadata.tables) == {"study", "dataset_version", "source_artifact"}


def test_dataset_versions_reference_studies_and_prevent_duplicates() -> None:
    """Dataset versions have lineage and duplicate-snapshot protections."""
    dataset_version = Base.metadata.tables["dataset_version"]

    foreign_keys = _constraint_names("dataset_version", ForeignKeyConstraint)
    unique_constraints = _constraint_names("dataset_version", UniqueConstraint)
    check_constraints = _constraint_names("dataset_version", CheckConstraint)

    assert "fk_dataset_version_study_id_study" in foreign_keys
    assert "uq_dataset_version_study_checksum" in unique_constraints
    assert "uq_dataset_version_study_version_label" in unique_constraints
    assert "ck_dataset_version_combined_checksum_sha256" in check_constraints
    assert dataset_version.c.study_id.foreign_keys.pop().target_fullname == "study.id"


def test_dataset_version_status_has_only_governed_values() -> None:
    """The status column accepts only the defined dataset lifecycle states."""
    status_type = Base.metadata.tables["dataset_version"].c.status.type

    assert isinstance(status_type, Enum)
    assert status_type.enums == [status.value for status in DatasetVersionStatus]


def test_source_artifacts_reference_versions_and_validate_integrity_fields() -> None:
    """Artifact records enforce ownership, identity, size, and checksum rules."""
    source_artifact = Base.metadata.tables["source_artifact"]

    foreign_keys = _constraint_names("source_artifact", ForeignKeyConstraint)
    unique_constraints = _constraint_names("source_artifact", UniqueConstraint)
    check_constraints = _constraint_names("source_artifact", CheckConstraint)

    assert "fk_source_artifact_dataset_version_id_dataset_version" in foreign_keys
    assert "uq_source_artifact_dataset_filename" in unique_constraints
    assert "ck_source_artifact_positive_byte_size" in check_constraints
    assert "ck_source_artifact_sha256" in check_constraints
    assert source_artifact.c.dataset_version_id.foreign_keys.pop().target_fullname == (
        "dataset_version.id"
    )

    kind_type = source_artifact.c.kind.type
    assert isinstance(kind_type, Enum)
    assert kind_type.enums == [kind.value for kind in ArtifactKind]
