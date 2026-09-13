"""Tests for SDTM demographics normalization."""

from pathlib import Path

import pytest

from trialops.datasets.dataset_json import DatasetJsonDataType, read_dataset_json
from trialops.datasets.demographics import (
    DemographicsImportError,
    DemographicsImportErrorCode,
    parse_demographics_subjects,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dataset_json" / "dm-valid.json"


def test_parser_normalizes_valid_demographics_subjects() -> None:
    """Generic named rows become immutable, typed subject records."""
    document = read_dataset_json(FIXTURE_PATH)

    subjects = parse_demographics_subjects(document)

    assert len(subjects) == 2
    assert subjects[0].source_record_number == 1
    assert subjects[0].study_id == "TRIALOPS-TEST-001"
    assert subjects[0].unique_subject_id == "TRIALOPS-SUBJECT-001"
    assert subjects[0].subject_id == "001"
    assert subjects[0].age == 34
    assert subjects[0].age_unit == "YEARS"
    assert subjects[0].sex == "F"
    assert subjects[0].race == "WHITE"
    assert subjects[0].planned_arm == "Placebo"
    assert subjects[0].actual_arm == "Placebo"


def test_parser_rejects_wrong_domain() -> None:
    """An AE or LB document cannot be processed as demographics."""
    document = read_dataset_json(FIXTURE_PATH).model_copy(
        update={"name": "AE", "item_group_oid": "AE"}
    )

    with pytest.raises(DemographicsImportError) as raised:
        parse_demographics_subjects(document)

    assert raised.value.code is DemographicsImportErrorCode.WRONG_DOMAIN


def test_parser_rejects_missing_required_column() -> None:
    """Every field needed by the normalized subject contract must be present."""
    document = read_dataset_json(FIXTURE_PATH)
    document = document.model_copy(update={"columns": document.columns[:-1]})

    with pytest.raises(DemographicsImportError) as raised:
        parse_demographics_subjects(document)

    assert raised.value.code is DemographicsImportErrorCode.MISSING_REQUIRED_COLUMNS
    assert raised.value.fields == ("ACTARM",)


def test_parser_rejects_column_type_mismatch() -> None:
    """The AGE column cannot claim to contain strings."""
    document = read_dataset_json(FIXTURE_PATH)
    columns = tuple(
        column.model_copy(update={"data_type": DatasetJsonDataType.STRING})
        if column.name == "AGE"
        else column
        for column in document.columns
    )
    document = document.model_copy(update={"columns": columns})

    with pytest.raises(DemographicsImportError) as raised:
        parse_demographics_subjects(document)

    assert raised.value.code is DemographicsImportErrorCode.COLUMN_TYPE_MISMATCH
    assert raised.value.fields == ("AGE",)


def test_parser_rejects_invalid_subject_value() -> None:
    """A negative AGE is structurally valid JSON but invalid demographics data."""
    document = read_dataset_json(FIXTURE_PATH)
    first_row = (*document.rows[0][:4], -1, *document.rows[0][5:])
    document = document.model_copy(update={"rows": (first_row, document.rows[1])})

    with pytest.raises(DemographicsImportError) as raised:
        parse_demographics_subjects(document)

    assert raised.value.code is DemographicsImportErrorCode.INVALID_RECORD
    assert raised.value.record_number == 1
    assert raised.value.fields == ("age",)


def test_parser_rejects_wrong_row_domain() -> None:
    """Every record must identify itself as part of DM."""
    document = read_dataset_json(FIXTURE_PATH)
    first_row = (document.rows[0][0], "AE", *document.rows[0][2:])
    document = document.model_copy(update={"rows": (first_row, document.rows[1])})

    with pytest.raises(DemographicsImportError) as raised:
        parse_demographics_subjects(document)

    assert raised.value.code is DemographicsImportErrorCode.INVALID_RECORD
    assert raised.value.fields == ("DOMAIN",)


def test_parser_rejects_wrong_row_study() -> None:
    """Every record must belong to the study declared by its document."""
    document = read_dataset_json(FIXTURE_PATH)
    first_row = ("OTHER-STUDY", *document.rows[0][1:])
    document = document.model_copy(update={"rows": (first_row, document.rows[1])})

    with pytest.raises(DemographicsImportError) as raised:
        parse_demographics_subjects(document)

    assert raised.value.code is DemographicsImportErrorCode.INVALID_RECORD
    assert raised.value.fields == ("STUDYID",)


def test_parser_rejects_duplicate_unique_subject_id() -> None:
    """A study cannot contain two DM rows for the same USUBJID."""
    document = read_dataset_json(FIXTURE_PATH)
    second_row = (
        *document.rows[1][:2],
        document.rows[0][2],
        *document.rows[1][3:],
    )
    document = document.model_copy(update={"rows": (document.rows[0], second_row)})

    with pytest.raises(DemographicsImportError) as raised:
        parse_demographics_subjects(document)

    assert raised.value.code is DemographicsImportErrorCode.DUPLICATE_SUBJECT
    assert raised.value.record_number == 2
    assert raised.value.fields == ("USUBJID",)
