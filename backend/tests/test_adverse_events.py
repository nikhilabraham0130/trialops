"""Tests for typed SDTM adverse-event normalization."""

from pathlib import Path

import pytest

from trialops.datasets.adverse_events import (
    AdverseEventImportError,
    AdverseEventImportErrorCode,
    AdverseEventSeverity,
    parse_adverse_events,
)
from trialops.datasets.dataset_json import (
    DatasetJsonDataType,
    DatasetJsonDocument,
    read_dataset_json,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dataset_json" / "ae-valid.json"


def _document() -> DatasetJsonDocument:
    return read_dataset_json(FIXTURE_PATH)


def _replace_first_row(
    document: DatasetJsonDocument, field: str, value: str | int
) -> DatasetJsonDocument:
    index = next(i for i, column in enumerate(document.columns) if column.name == field)
    first_row = list(document.rows[0])
    first_row[index] = value
    return document.model_copy(update={"rows": (tuple(first_row), document.rows[1])})


def test_parser_normalizes_events_by_column_name() -> None:
    """AESEQ appears first in the fixture, proving positions are not hard-coded."""
    events = parse_adverse_events(_document())

    assert len(events) == 2
    assert events[0].source_record_number == 1
    assert events[0].study_id == "TRIALOPS-TEST-001"
    assert events[0].unique_subject_id == "TRIALOPS-SUBJECT-001"
    assert events[0].event_sequence == 1
    assert events[0].reported_term == "Headache"
    assert events[0].preferred_term == "HEADACHE"
    assert events[0].severity is AdverseEventSeverity.MILD
    assert events[0].serious_flag == "N"
    assert events[0].start_date_text == "2026-09-01"
    assert events[0].end_date_text == "2026-09-02"
    assert events[1].event_sequence == 2
    assert events[1].severity is AdverseEventSeverity.SEVERE
    assert events[1].serious_flag == "Y"
    assert events[1].end_date_text is None


def test_parser_rejects_wrong_domain() -> None:
    document = _document().model_copy(update={"name": "LB", "item_group_oid": "LB"})

    with pytest.raises(AdverseEventImportError) as raised:
        parse_adverse_events(document)

    assert raised.value.code is AdverseEventImportErrorCode.WRONG_DOMAIN


def test_parser_rejects_missing_required_column() -> None:
    document = _document()
    document = document.model_copy(update={"columns": document.columns[:-1]})

    with pytest.raises(AdverseEventImportError) as raised:
        parse_adverse_events(document)

    assert raised.value.code is AdverseEventImportErrorCode.MISSING_REQUIRED_COLUMNS
    assert raised.value.fields == ("AEENDTC",)


def test_parser_rejects_column_type_mismatch() -> None:
    document = _document()
    columns = tuple(
        column.model_copy(update={"data_type": DatasetJsonDataType.STRING})
        if column.name == "AESEQ"
        else column
        for column in document.columns
    )

    with pytest.raises(AdverseEventImportError) as raised:
        parse_adverse_events(document.model_copy(update={"columns": columns}))

    assert raised.value.code is AdverseEventImportErrorCode.COLUMN_TYPE_MISMATCH
    assert raised.value.fields == ("AESEQ",)


@pytest.mark.parametrize(
    ("field", "value", "expected_field"),
    [
        ("AESEQ", 0, "event_sequence"),
        ("USUBJID", "", "unique_subject_id"),
        ("AETERM", "", "reported_term"),
        ("AEDECOD", "", "preferred_term"),
        ("AESEV", "GRADE 3", "severity"),
        ("AESER", "YES", "serious_flag"),
        ("AESTDTC", "", "start_date_text"),
        ("AEENDTC", 5, "end_date_text"),
    ],
)
def test_parser_rejects_invalid_event_values(
    field: str, value: str | int, expected_field: str
) -> None:
    document = _replace_first_row(_document(), field, value)

    with pytest.raises(AdverseEventImportError) as raised:
        parse_adverse_events(document)

    assert raised.value.code is AdverseEventImportErrorCode.INVALID_RECORD
    assert raised.value.record_number == 1
    assert raised.value.fields == (expected_field,)


@pytest.mark.parametrize(
    ("field", "value"),
    [("DOMAIN", "DM"), ("STUDYID", "OTHER-STUDY")],
)
def test_parser_rejects_wrong_row_identity(field: str, value: str) -> None:
    document = _replace_first_row(_document(), field, value)

    with pytest.raises(AdverseEventImportError) as raised:
        parse_adverse_events(document)

    assert raised.value.code is AdverseEventImportErrorCode.INVALID_RECORD
    assert raised.value.record_number == 1
    assert raised.value.fields == (field,)


def test_parser_rejects_duplicate_subject_event_sequence() -> None:
    document = _document()
    second_row = list(document.rows[1])
    second_row[0] = 1
    document = document.model_copy(update={"rows": (document.rows[0], tuple(second_row))})

    with pytest.raises(AdverseEventImportError) as raised:
        parse_adverse_events(document)

    assert raised.value.code is AdverseEventImportErrorCode.DUPLICATE_EVENT
    assert raised.value.record_number == 2
    assert raised.value.fields == ("USUBJID", "AESEQ")


def test_same_sequence_may_belong_to_different_subjects() -> None:
    document = _document()
    second_row = list(document.rows[1])
    second_row[0] = 1
    second_row[2] = "TRIALOPS-SUBJECT-002"
    document = document.model_copy(update={"rows": (document.rows[0], tuple(second_row))})

    events = parse_adverse_events(document)

    assert len(events) == 2
    assert events[0].event_sequence == events[1].event_sequence
    assert events[0].unique_subject_id != events[1].unique_subject_id
