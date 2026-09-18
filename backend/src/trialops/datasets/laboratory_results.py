"""Domain-specific normalization for SDTM laboratory-result data."""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
)

from trialops.datasets.dataset_json import DatasetJsonDataType, DatasetJsonDocument
from trialops.datasets.table import MissingRequiredColumnsError, iter_named_rows, require_columns

StrictNonEmptyString = Annotated[StrictStr, Field(min_length=1)]
PositiveSequence = Annotated[StrictInt, Field(ge=1)]

LB_COLUMN_TYPES: dict[str, DatasetJsonDataType] = {
    "STUDYID": DatasetJsonDataType.STRING,
    "DOMAIN": DatasetJsonDataType.STRING,
    "USUBJID": DatasetJsonDataType.STRING,
    "LBSEQ": DatasetJsonDataType.INTEGER,
    "LBTESTCD": DatasetJsonDataType.STRING,
    "LBTEST": DatasetJsonDataType.STRING,
    "LBSTRESN": DatasetJsonDataType.FLOAT,
    "LBSTRESU": DatasetJsonDataType.STRING,
    "LBSTNRLO": DatasetJsonDataType.INTEGER,
    "LBSTNRHI": DatasetJsonDataType.INTEGER,
    "LBNRIND": DatasetJsonDataType.STRING,
    "LBBLFL": DatasetJsonDataType.STRING,
    "LBDTC": DatasetJsonDataType.DATETIME,
}


class NormalRangeIndicator(StrEnum):
    """Normal-range classifications present in the pilot LB source."""

    NORMAL = "NORMAL"
    LOW = "LOW"
    HIGH = "HIGH"
    ABNORMAL = "ABNORMAL"


class LaboratoryResultImportErrorCode(StrEnum):
    """Stable reasons an LB document cannot be normalized."""

    WRONG_DOMAIN = "WRONG_DOMAIN"
    MISSING_REQUIRED_COLUMNS = "MISSING_REQUIRED_COLUMNS"
    COLUMN_TYPE_MISMATCH = "COLUMN_TYPE_MISMATCH"
    INVALID_RECORD = "INVALID_RECORD"
    DUPLICATE_RESULT = "DUPLICATE_RESULT"


class LaboratoryResultImportError(ValueError):
    """Raised when an LB document violates its domain-specific contract."""

    def __init__(
        self,
        code: LaboratoryResultImportErrorCode,
        message: str,
        *,
        record_number: int | None = None,
        fields: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.record_number = record_number
        self.fields = fields


class LaboratoryResult(BaseModel):
    """One typed LB row, preserving source identity and missing-value meaning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_number: int = Field(ge=1)
    study_id: StrictNonEmptyString
    unique_subject_id: StrictNonEmptyString
    result_sequence: PositiveSequence
    test_code: StrictNonEmptyString
    test_name: StrictNonEmptyString
    standard_result: Decimal | None
    standard_unit: StrictStr | None
    lower_reference_limit: Decimal | None
    upper_reference_limit: Decimal | None
    range_indicator: NormalRangeIndicator | None
    baseline_flag: Literal["Y"] | None
    observed_at_text: StrictNonEmptyString

    @field_validator(
        "standard_result", "lower_reference_limit", "upper_reference_limit", mode="before"
    )
    @classmethod
    def require_numeric_source_value(cls, value: object) -> Decimal | None:
        """Keep exact numeric precision and reject strings other than missing."""
        if value is None or value == "":
            return None
        if type(value) is int:
            return Decimal(value)
        if isinstance(value, Decimal) and value.is_finite():
            return value
        raise ValueError("A numeric result or reference limit must be an integer or decimal.")


def _missing_to_none(value: object) -> object | None:
    """Treat the source's empty strings and JSON nulls as absent values."""
    return None if value is None or value == "" else value


def parse_laboratory_results(document: DatasetJsonDocument) -> tuple[LaboratoryResult, ...]:
    """Validate and normalize LB rows without assigning clinical meaning yet."""
    if document.name != "LB":
        raise LaboratoryResultImportError(
            LaboratoryResultImportErrorCode.WRONG_DOMAIN,
            f"Expected LB but received {document.name}.",
        )

    try:
        require_columns(document, LB_COLUMN_TYPES)
    except MissingRequiredColumnsError as exc:
        raise LaboratoryResultImportError(
            LaboratoryResultImportErrorCode.MISSING_REQUIRED_COLUMNS,
            str(exc),
            fields=exc.missing_columns,
        ) from exc

    columns_by_name = {column.name: column for column in document.columns}
    mismatched_types = tuple(
        sorted(
            name
            for name, expected_type in LB_COLUMN_TYPES.items()
            if columns_by_name[name].data_type is not expected_type
        )
    )
    if mismatched_types:
        raise LaboratoryResultImportError(
            LaboratoryResultImportErrorCode.COLUMN_TYPE_MISMATCH,
            f"LB columns have unexpected data types: {', '.join(mismatched_types)}",
            fields=mismatched_types,
        )

    results: list[LaboratoryResult] = []
    result_keys: set[tuple[str, int]] = set()
    for row in iter_named_rows(document):
        if row.values["DOMAIN"] != "LB":
            raise LaboratoryResultImportError(
                LaboratoryResultImportErrorCode.INVALID_RECORD,
                "LB row has an unexpected DOMAIN value.",
                record_number=row.record_number,
                fields=("DOMAIN",),
            )
        if row.values["STUDYID"] != document.study_oid:
            raise LaboratoryResultImportError(
                LaboratoryResultImportErrorCode.INVALID_RECORD,
                "LB row STUDYID does not match the document study OID.",
                record_number=row.record_number,
                fields=("STUDYID",),
            )

        try:
            result = LaboratoryResult.model_validate(
                {
                    "source_record_number": row.record_number,
                    "study_id": row.values["STUDYID"],
                    "unique_subject_id": row.values["USUBJID"],
                    "result_sequence": row.values["LBSEQ"],
                    "test_code": row.values["LBTESTCD"],
                    "test_name": row.values["LBTEST"],
                    "standard_result": row.values["LBSTRESN"],
                    "standard_unit": _missing_to_none(row.values["LBSTRESU"]),
                    "lower_reference_limit": row.values["LBSTNRLO"],
                    "upper_reference_limit": row.values["LBSTNRHI"],
                    "range_indicator": _missing_to_none(row.values["LBNRIND"]),
                    "baseline_flag": _missing_to_none(row.values["LBBLFL"]),
                    "observed_at_text": row.values["LBDTC"],
                }
            )
        except ValidationError as exc:
            fields = tuple(sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]}))
            raise LaboratoryResultImportError(
                LaboratoryResultImportErrorCode.INVALID_RECORD,
                "LB row contains invalid laboratory values.",
                record_number=row.record_number,
                fields=fields,
            ) from exc

        result_key = (result.unique_subject_id, result.result_sequence)
        if result_key in result_keys:
            raise LaboratoryResultImportError(
                LaboratoryResultImportErrorCode.DUPLICATE_RESULT,
                "LB contains a duplicate USUBJID and LBSEQ pair.",
                record_number=row.record_number,
                fields=("USUBJID", "LBSEQ"),
            )

        result_keys.add(result_key)
        results.append(result)

    return tuple(results)
