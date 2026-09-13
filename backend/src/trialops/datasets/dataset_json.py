"""Reader and structural validation for Dataset-JSON files."""

import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from json import JSONDecodeError
from pathlib import Path
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)

DatasetJsonValue = StrictStr | StrictInt | Decimal | StrictBool | None
NonEmptyString = Annotated[str, Field(min_length=1)]


class DatasetJsonReadErrorCode(StrEnum):
    """Stable reasons that a Dataset-JSON file cannot be read."""

    FILE_UNAVAILABLE = "FILE_UNAVAILABLE"
    INVALID_ENCODING = "INVALID_ENCODING"
    INVALID_JSON = "INVALID_JSON"
    INVALID_STRUCTURE = "INVALID_STRUCTURE"


class DatasetJsonReadError(ValueError):
    """Raised when Dataset-JSON cannot be safely converted into a document."""

    def __init__(self, code: DatasetJsonReadErrorCode, message: str, *, filename: str) -> None:
        super().__init__(message)
        self.code = code
        self.filename = filename


class DatasetJsonDataType(StrEnum):
    """Dataset-JSON data types supported by the initial CDISC package."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    DECIMAL = "decimal"
    DATE = "date"
    DATETIME = "datetime"


class DatasetJsonModel(BaseModel):
    """Strict, immutable base for Dataset-JSON structures."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DatasetJsonSourceSystem(DatasetJsonModel):
    """Software that created the Dataset-JSON file."""

    name: NonEmptyString
    version: NonEmptyString


class DatasetJsonColumn(DatasetJsonModel):
    """Metadata that describes one position in every data row."""

    item_oid: NonEmptyString = Field(alias="itemOID")
    name: NonEmptyString
    label: NonEmptyString
    data_type: DatasetJsonDataType = Field(alias="dataType")
    length: int | None = Field(default=None, gt=0)
    key_sequence: int | None = Field(default=None, alias="keySequence", ge=1)
    display_format: str | None = Field(default=None, alias="displayFormat")


class DatasetJsonDocument(DatasetJsonModel):
    """Validated metadata and rows from one Dataset-JSON domain file."""

    creation_datetime: datetime = Field(alias="datasetJSONCreationDateTime")
    dataset_json_version: NonEmptyString = Field(alias="datasetJSONVersion")
    file_oid: NonEmptyString = Field(alias="fileOID")
    database_modified_datetime: datetime = Field(alias="dbLastModifiedDateTime")
    originator: NonEmptyString
    source_system: DatasetJsonSourceSystem = Field(alias="sourceSystem")
    study_oid: NonEmptyString = Field(alias="studyOID")
    metadata_version_oid: NonEmptyString = Field(alias="metaDataVersionOID")
    metadata_reference: NonEmptyString = Field(alias="metaDataRef")
    item_group_oid: NonEmptyString = Field(alias="itemGroupOID")
    records: int = Field(ge=0)
    name: NonEmptyString
    label: NonEmptyString
    columns: tuple[DatasetJsonColumn, ...] = Field(min_length=1)
    rows: tuple[tuple[DatasetJsonValue, ...], ...]

    @model_validator(mode="after")
    def validate_table_shape(self) -> Self:
        """Ensure metadata and positional row values describe one table."""
        if self.records != len(self.rows):
            raise ValueError("Declared record count does not match the number of rows.")

        column_names = [column.name.casefold() for column in self.columns]
        if len(column_names) != len(set(column_names)):
            raise ValueError("Column names must be unique.")

        item_oids = [column.item_oid.casefold() for column in self.columns]
        if len(item_oids) != len(set(item_oids)):
            raise ValueError("Column item OIDs must be unique.")

        expected_values = len(self.columns)
        for record_number, row in enumerate(self.rows, start=1):
            if len(row) != expected_values:
                raise ValueError(
                    f"Row {record_number} has {len(row)} values; expected {expected_values}."
                )

        if self.item_group_oid.casefold() != self.name.casefold():
            raise ValueError("Item-group OID does not match the dataset name.")

        return self


class _DuplicateJsonPropertyError(ValueError):
    """Internal signal raised when a JSON object repeats a property name."""


def _reject_duplicate_properties(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build a JSON object while rejecting ambiguous duplicate properties."""
    parsed: dict[str, object] = {}
    for key, value in pairs:
        if key in parsed:
            raise _DuplicateJsonPropertyError(f"Duplicate JSON property: {key}")
        parsed[key] = value
    return parsed


def read_dataset_json(path: Path) -> DatasetJsonDocument:
    """Read one UTF-8 Dataset-JSON file and validate its table structure."""
    try:
        with path.open("r", encoding="utf-8") as source_file:
            payload = json.load(
                source_file,
                parse_float=Decimal,
                object_pairs_hook=_reject_duplicate_properties,
            )
    except UnicodeDecodeError as exc:
        raise DatasetJsonReadError(
            DatasetJsonReadErrorCode.INVALID_ENCODING,
            f"Dataset-JSON file is not valid UTF-8: {path.name}",
            filename=path.name,
        ) from exc
    except (JSONDecodeError, _DuplicateJsonPropertyError) as exc:
        raise DatasetJsonReadError(
            DatasetJsonReadErrorCode.INVALID_JSON,
            f"Dataset-JSON file contains invalid JSON: {path.name}",
            filename=path.name,
        ) from exc
    except OSError as exc:
        raise DatasetJsonReadError(
            DatasetJsonReadErrorCode.FILE_UNAVAILABLE,
            f"Dataset-JSON file is unavailable: {path.name}",
            filename=path.name,
        ) from exc

    try:
        return DatasetJsonDocument.model_validate(payload)
    except ValidationError as exc:
        raise DatasetJsonReadError(
            DatasetJsonReadErrorCode.INVALID_STRUCTURE,
            f"Dataset-JSON structure is invalid: {path.name}",
            filename=path.name,
        ) from exc
