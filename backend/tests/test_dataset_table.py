"""Tests for named access to Dataset-JSON rows."""

from collections.abc import MutableMapping
from pathlib import Path
from typing import cast

import pytest

from trialops.datasets.dataset_json import DatasetJsonValue, read_dataset_json
from trialops.datasets.table import (
    MissingRequiredColumnsError,
    iter_named_rows,
    require_columns,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dataset_json" / "dm-valid.json"


def test_named_rows_pair_values_with_metadata_columns() -> None:
    """Column names, rather than assumed positions, identify every value."""
    document = read_dataset_json(FIXTURE_PATH)

    rows = tuple(iter_named_rows(document))

    assert len(rows) == 2
    assert rows[0].record_number == 1
    assert rows[0].values["STUDYID"] == "TRIALOPS-TEST-001"
    assert rows[0].values["USUBJID"] == "TRIALOPS-SUBJECT-001"
    assert rows[0].values["AGE"] == 34
    assert rows[0].values["ARM"] == "Placebo"
    assert rows[1].record_number == 2
    assert rows[1].values["USUBJID"] == "TRIALOPS-SUBJECT-002"


def test_named_row_values_are_read_only() -> None:
    """Downstream code cannot silently change values read from the source."""
    document = read_dataset_json(FIXTURE_PATH)
    row = next(iter_named_rows(document))
    mutable_view = cast(MutableMapping[str, DatasetJsonValue], row.values)

    with pytest.raises(TypeError):
        mutable_view["AGE"] = 99


def test_required_columns_accept_complete_document() -> None:
    """An importer can declare columns without depending on their positions."""
    document = read_dataset_json(FIXTURE_PATH)

    require_columns(document, ("AGE", "STUDYID", "USUBJID"))


def test_required_columns_report_all_missing_names() -> None:
    """One deterministic error lists every column an importer cannot find."""
    document = read_dataset_json(FIXTURE_PATH)

    with pytest.raises(MissingRequiredColumnsError) as raised:
        require_columns(document, ("SITEID", "COUNTRY", "USUBJID"))

    assert raised.value.dataset_name == "DM"
    assert raised.value.missing_columns == ("COUNTRY", "SITEID")
    assert str(raised.value) == "Dataset DM is missing required columns: COUNTRY, SITEID"
