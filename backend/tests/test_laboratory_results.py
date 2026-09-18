"""Tests for typed SDTM laboratory-result normalization."""

from decimal import Decimal
from pathlib import Path

import pytest

from trialops.datasets.dataset_json import (
    DatasetJsonDataType,
    DatasetJsonDocument,
    read_dataset_json,
)
from trialops.datasets.laboratory_results import (
    LaboratoryResultImportError,
    LaboratoryResultImportErrorCode,
    NormalRangeIndicator,
    parse_laboratory_results,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dataset_json" / "lb-valid.json"


def _document() -> DatasetJsonDocument:
    return read_dataset_json(FIXTURE_PATH)


def _replace_first_row(
    document: DatasetJsonDocument,
    field: str,
    value: str | int | Decimal | bool | None,
) -> DatasetJsonDocument:
    index = next(i for i, column in enumerate(document.columns) if column.name == field)
    first_row = list(document.rows[0])
    first_row[index] = value
    return document.model_copy(update={"rows": (tuple(first_row), document.rows[1])})


def test_parser_normalizes_results_by_column_name_and_preserves_precision() -> None:
    """The fixture puts LBSEQ first, so field positions cannot be assumed."""
    results = parse_laboratory_results(_document())

    assert len(results) == 2
    assert results[0].source_record_number == 1
    assert results[0].study_id == "TRIALOPS-TEST-001"
    assert results[0].unique_subject_id == "TRIALOPS-SUBJECT-001"
    assert results[0].result_sequence == 1
    assert results[0].test_code == "ALT"
    assert results[0].test_name == "Alanine Aminotransferase"
    assert results[0].standard_result == Decimal("90.5")
    assert results[0].standard_unit == "U/L"
    assert results[0].lower_reference_limit == Decimal(0)
    assert results[0].upper_reference_limit == Decimal(40)
    assert results[0].range_indicator is NormalRangeIndicator.HIGH
    assert results[0].baseline_flag == "Y"
    assert results[0].observed_at_text == "2026-09-01T09:30"


def test_parser_preserves_missing_numeric_and_classification_values() -> None:
    """Missing values stay missing rather than becoming zero or normal."""
    second = parse_laboratory_results(_document())[1]

    assert second.standard_result is None
    assert second.standard_unit is None
    assert second.lower_reference_limit is None
    assert second.upper_reference_limit is None
    assert second.range_indicator is None
    assert second.baseline_flag is None


def test_parser_rejects_wrong_domain() -> None:
    document = _document().model_copy(update={"name": "AE", "item_group_oid": "AE"})

    with pytest.raises(LaboratoryResultImportError) as raised:
        parse_laboratory_results(document)

    assert raised.value.code is LaboratoryResultImportErrorCode.WRONG_DOMAIN


def test_parser_rejects_missing_required_column() -> None:
    document = _document()
    document = document.model_copy(update={"columns": document.columns[:-1]})

    with pytest.raises(LaboratoryResultImportError) as raised:
        parse_laboratory_results(document)

    assert raised.value.code is LaboratoryResultImportErrorCode.MISSING_REQUIRED_COLUMNS
    assert raised.value.fields == ("LBDTC",)


def test_parser_rejects_column_type_mismatch() -> None:
    document = _document()
    columns = tuple(
        column.model_copy(update={"data_type": DatasetJsonDataType.STRING})
        if column.name == "LBSTRESN"
        else column
        for column in document.columns
    )

    with pytest.raises(LaboratoryResultImportError) as raised:
        parse_laboratory_results(document.model_copy(update={"columns": columns}))

    assert raised.value.code is LaboratoryResultImportErrorCode.COLUMN_TYPE_MISMATCH
    assert raised.value.fields == ("LBSTRESN",)


@pytest.mark.parametrize(
    ("field", "value", "expected_field"),
    [
        ("LBSEQ", 0, "result_sequence"),
        ("USUBJID", "", "unique_subject_id"),
        ("LBTESTCD", "", "test_code"),
        ("LBTEST", "", "test_name"),
        ("LBSTRESN", "90.5", "standard_result"),
        ("LBSTRESN", True, "standard_result"),
        ("LBSTRESN", Decimal("NaN"), "standard_result"),
        ("LBSTNRLO", "not a number", "lower_reference_limit"),
        ("LBSTNRHI", "40", "upper_reference_limit"),
        ("LBSTRESU", 5, "standard_unit"),
        ("LBNRIND", "UNKNOWN", "range_indicator"),
        ("LBBLFL", "N", "baseline_flag"),
        ("LBDTC", "", "observed_at_text"),
    ],
)
def test_parser_rejects_invalid_result_values(
    field: str,
    value: str | int | Decimal | bool | None,
    expected_field: str,
) -> None:
    document = _replace_first_row(_document(), field, value)

    with pytest.raises(LaboratoryResultImportError) as raised:
        parse_laboratory_results(document)

    assert raised.value.code is LaboratoryResultImportErrorCode.INVALID_RECORD
    assert raised.value.record_number == 1
    assert raised.value.fields == (expected_field,)


@pytest.mark.parametrize(
    ("field", "value"),
    [("DOMAIN", "DM"), ("STUDYID", "OTHER-STUDY")],
)
def test_parser_rejects_wrong_row_identity(field: str, value: str) -> None:
    document = _replace_first_row(_document(), field, value)

    with pytest.raises(LaboratoryResultImportError) as raised:
        parse_laboratory_results(document)

    assert raised.value.code is LaboratoryResultImportErrorCode.INVALID_RECORD
    assert raised.value.record_number == 1
    assert raised.value.fields == (field,)


def test_parser_rejects_duplicate_subject_result_sequence() -> None:
    document = _document()
    second_row = list(document.rows[1])
    second_row[0] = 1
    document = document.model_copy(update={"rows": (document.rows[0], tuple(second_row))})

    with pytest.raises(LaboratoryResultImportError) as raised:
        parse_laboratory_results(document)

    assert raised.value.code is LaboratoryResultImportErrorCode.DUPLICATE_RESULT
    assert raised.value.record_number == 2
    assert raised.value.fields == ("USUBJID", "LBSEQ")


def test_same_sequence_may_belong_to_different_subjects() -> None:
    document = _document()
    second_row = list(document.rows[1])
    second_row[0] = 1
    second_row[2] = "TRIALOPS-SUBJECT-002"
    document = document.model_copy(update={"rows": (document.rows[0], tuple(second_row))})

    results = parse_laboratory_results(document)

    assert len(results) == 2
    assert results[0].result_sequence == results[1].result_sequence
    assert results[0].unique_subject_id != results[1].unique_subject_id
