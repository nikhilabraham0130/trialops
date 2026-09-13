"""Tests for reading and structurally validating Dataset-JSON."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from trialops.datasets.dataset_json import (
    DatasetJsonDataType,
    DatasetJsonReadError,
    DatasetJsonReadErrorCode,
    read_dataset_json,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dataset_json" / "dm-valid.json"


def test_reader_loads_valid_trialops_fixture() -> None:
    """The reader preserves metadata and positional row values."""
    document = read_dataset_json(FIXTURE_PATH)

    assert document.name == "DM"
    assert document.study_oid == "TRIALOPS-TEST-001"
    assert document.records == 2
    assert document.creation_datetime == datetime(2026, 9, 12, 12, 0)
    assert document.columns[1].name == "USUBJID"
    assert document.columns[1].key_sequence == 1
    assert document.columns[2].data_type is DatasetJsonDataType.INTEGER
    assert document.rows[0] == ("TRIALOPS-TEST-001", "TRIALOPS-SUBJECT-001", 34)


def test_reader_reports_missing_file(tmp_path: Path) -> None:
    """A missing source file receives a stable error code."""
    missing_path = tmp_path / "missing.json"

    with pytest.raises(DatasetJsonReadError) as raised:
        read_dataset_json(missing_path)

    assert raised.value.code is DatasetJsonReadErrorCode.FILE_UNAVAILABLE
    assert raised.value.filename == "missing.json"


def test_reader_rejects_non_utf8_file(tmp_path: Path) -> None:
    """Dataset-JSON input must use the documented UTF-8 encoding."""
    path = tmp_path / "invalid-encoding.json"
    path.write_bytes(b"\xff")

    with pytest.raises(DatasetJsonReadError) as raised:
        read_dataset_json(path)

    assert raised.value.code is DatasetJsonReadErrorCode.INVALID_ENCODING


def test_reader_rejects_invalid_json(tmp_path: Path) -> None:
    """Truncated or otherwise invalid JSON is rejected before validation."""
    path = tmp_path / "invalid.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(DatasetJsonReadError) as raised:
        read_dataset_json(path)

    assert raised.value.code is DatasetJsonReadErrorCode.INVALID_JSON


def test_reader_rejects_duplicate_json_property(tmp_path: Path) -> None:
    """Repeated JSON property names cannot silently overwrite each other."""
    path = tmp_path / "duplicate-property.json"
    path.write_text('{"name": "DM", "name": "AE"}', encoding="utf-8")

    with pytest.raises(DatasetJsonReadError) as raised:
        read_dataset_json(path)

    assert raised.value.code is DatasetJsonReadErrorCode.INVALID_JSON


def test_reader_rejects_record_count_mismatch(tmp_path: Path) -> None:
    """The declared record count must equal the actual number of rows."""
    path = _write_document(tmp_path, records=2)

    with pytest.raises(DatasetJsonReadError) as raised:
        read_dataset_json(path)

    assert raised.value.code is DatasetJsonReadErrorCode.INVALID_STRUCTURE


def test_reader_rejects_wrong_row_width(tmp_path: Path) -> None:
    """Every row must contain exactly one value for every column."""
    columns = [_column("DM.STUDYID", "STUDYID"), _column("DM.USUBJID", "USUBJID")]
    path = _write_document(
        tmp_path,
        columns=columns,
        rows=[["TRIALOPS-TEST-001"]],
    )

    with pytest.raises(DatasetJsonReadError) as raised:
        read_dataset_json(path)

    assert raised.value.code is DatasetJsonReadErrorCode.INVALID_STRUCTURE


def test_reader_rejects_duplicate_column_names(tmp_path: Path) -> None:
    """Column names must map each row position to one unambiguous field."""
    columns = [_column("DM.STUDYID", "STUDYID"), _column("DM.SUBJECT", "studyid")]
    path = _write_document(tmp_path, columns=columns, rows=[["STUDY", "SUBJECT"]])

    with pytest.raises(DatasetJsonReadError) as raised:
        read_dataset_json(path)

    assert raised.value.code is DatasetJsonReadErrorCode.INVALID_STRUCTURE


def test_reader_rejects_duplicate_item_oids(tmp_path: Path) -> None:
    """Column metadata identifiers must also be unique."""
    columns = [_column("DM.STUDYID", "STUDYID"), _column("dm.studyid", "SUBJECT")]
    path = _write_document(tmp_path, columns=columns, rows=[["STUDY", "SUBJECT"]])

    with pytest.raises(DatasetJsonReadError) as raised:
        read_dataset_json(path)

    assert raised.value.code is DatasetJsonReadErrorCode.INVALID_STRUCTURE


def test_reader_rejects_dataset_name_mismatch(tmp_path: Path) -> None:
    """The item-group identifier and domain name must identify the same table."""
    path = _write_document(tmp_path, item_group_oid="AE")

    with pytest.raises(DatasetJsonReadError) as raised:
        read_dataset_json(path)

    assert raised.value.code is DatasetJsonReadErrorCode.INVALID_STRUCTURE


def _column(item_oid: str, name: str) -> dict[str, object]:
    """Create one TrialOps-owned column definition for a test document."""
    return {
        "itemOID": item_oid,
        "name": name,
        "label": name.title(),
        "dataType": "string",
        "length": 30,
    }


def _write_document(
    tmp_path: Path,
    *,
    records: int = 1,
    item_group_oid: str = "DM",
    columns: list[dict[str, object]] | None = None,
    rows: list[list[object]] | None = None,
) -> Path:
    """Write a minimal, independent Dataset-JSON document for one test."""
    document: dict[str, object] = {
        "datasetJSONCreationDateTime": "2026-09-12T12:00:00",
        "datasetJSONVersion": "1.1.0",
        "fileOID": "TRIALOPS-TEST-001.dm",
        "dbLastModifiedDateTime": "2026-09-12T11:30:00",
        "originator": "TrialOps",
        "sourceSystem": {"name": "TrialOps Fixture Generator", "version": "1.0"},
        "studyOID": "TRIALOPS-TEST-001",
        "metaDataVersionOID": "TRIALOPS.SDTMIG.3.1.2",
        "metaDataRef": "define.xml",
        "itemGroupOID": item_group_oid,
        "records": records,
        "name": "DM",
        "label": "TrialOps-owned test document",
        "columns": columns if columns is not None else [_column("DM.STUDYID", "STUDYID")],
        "rows": rows if rows is not None else [["TRIALOPS-TEST-001"]],
    }
    path = tmp_path / "document.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path
