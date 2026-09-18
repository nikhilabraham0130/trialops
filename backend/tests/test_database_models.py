"""Tests for foundational SQLAlchemy table models."""

from sqlalchemy import CheckConstraint, Enum, ForeignKeyConstraint, Numeric, UniqueConstraint

from trialops.datasets.adverse_events import AdverseEventSeverity
from trialops.datasets.laboratory_results import NormalRangeIndicator
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
    """Alembic sees the catalog and initial normalized clinical table."""
    assert set(Base.metadata.tables) == {
        "study",
        "dataset_version",
        "source_artifact",
        "dm_subject",
        "ae_event",
        "lb_result",
    }


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


def test_dm_subjects_are_versioned_and_protected_from_duplicates() -> None:
    """Every DM row has source lineage and one identity within its dataset."""
    dm_subject = Base.metadata.tables["dm_subject"]

    foreign_keys = _constraint_names("dm_subject", ForeignKeyConstraint)
    unique_constraints = _constraint_names("dm_subject", UniqueConstraint)
    check_constraints = _constraint_names("dm_subject", CheckConstraint)

    assert "fk_dm_subject_dataset_version_id_dataset_version" in foreign_keys
    assert "uq_dm_subject_dataset_record_number" in unique_constraints
    assert "uq_dm_subject_dataset_unique_subject" in unique_constraints
    assert "ck_dm_subject_positive_source_record_number" in check_constraints
    assert "ck_dm_subject_age_range" in check_constraints
    assert "ck_dm_subject_nonempty_unique_subject_id" in check_constraints
    assert "ck_dm_subject_nonempty_subject_id" in check_constraints
    assert dm_subject.c.dataset_version_id.foreign_keys.pop().target_fullname == (
        "dataset_version.id"
    )
    assert all(not column.nullable for column in dm_subject.columns)


def test_ae_events_reference_dm_subjects_in_the_same_version() -> None:
    """The database rejects an AE row without a matching versioned DM subject."""
    ae_event = Base.metadata.tables["ae_event"]
    foreign_keys = [
        constraint
        for constraint in ae_event.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]

    assert len(foreign_keys) == 1
    assert str(foreign_keys[0].name) == "fk_ae_event_dataset_subject_dm_subject"
    assert {element.target_fullname for element in foreign_keys[0].elements} == {
        "dm_subject.dataset_version_id",
        "dm_subject.unique_subject_id",
    }

    unique_constraints = _constraint_names("ae_event", UniqueConstraint)
    check_constraints = _constraint_names("ae_event", CheckConstraint)
    assert "uq_ae_event_dataset_record_number" in unique_constraints
    assert "uq_ae_event_dataset_subject_sequence" in unique_constraints
    assert "ck_ae_event_positive_source_record_number" in check_constraints
    assert "ck_ae_event_positive_event_sequence" in check_constraints
    assert "ck_ae_event_serious_flag_values" in check_constraints

    severity_type = ae_event.c.severity.type
    assert isinstance(severity_type, Enum)
    assert severity_type.enums == [severity.value for severity in AdverseEventSeverity]
    assert ae_event.c.end_date_text.nullable
    assert all(not column.nullable for column in ae_event.columns if column.name != "end_date_text")


def test_lb_results_reference_dm_subjects_in_the_same_version() -> None:
    """LB rows are version-linked and retain missing numeric values as NULL."""
    lb_result = Base.metadata.tables["lb_result"]
    foreign_keys = [
        constraint
        for constraint in lb_result.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]
    assert len(foreign_keys) == 1
    assert str(foreign_keys[0].name) == "fk_lb_result_dataset_subject_dm_subject"
    assert {element.target_fullname for element in foreign_keys[0].elements} == {
        "dm_subject.dataset_version_id",
        "dm_subject.unique_subject_id",
    }

    unique_constraints = _constraint_names("lb_result", UniqueConstraint)
    check_constraints = _constraint_names("lb_result", CheckConstraint)
    assert "uq_lb_result_dataset_record_number" in unique_constraints
    assert "uq_lb_result_dataset_subject_sequence" in unique_constraints
    assert "ck_lb_result_positive_source_record_number" in check_constraints
    assert "ck_lb_result_positive_result_sequence" in check_constraints
    assert "ck_lb_result_baseline_flag_value" in check_constraints

    for name in ("standard_result", "lower_reference_limit", "upper_reference_limit"):
        assert isinstance(lb_result.c[name].type, Numeric)
        assert lb_result.c[name].nullable

    range_type = lb_result.c.range_indicator.type
    assert isinstance(range_type, Enum)
    assert range_type.enums == [indicator.value for indicator in NormalRangeIndicator]
    assert lb_result.c.baseline_flag.nullable
    assert all(
        not column.nullable
        for column in lb_result.columns
        if column.name
        not in {
            "standard_result",
            "standard_unit",
            "lower_reference_limit",
            "upper_reference_limit",
            "range_indicator",
            "baseline_flag",
        }
    )
