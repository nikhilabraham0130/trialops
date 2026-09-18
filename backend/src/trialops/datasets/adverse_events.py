"""Domain-specific normalization for SDTM adverse-event data."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from trialops.datasets.dataset_json import DatasetJsonDataType, DatasetJsonDocument
from trialops.datasets.table import MissingRequiredColumnsError, iter_named_rows, require_columns

StrictNonEmptyString = Annotated[StrictStr, Field(min_length=1)]
PositiveSequence = Annotated[StrictInt, Field(ge=1)]

AE_COLUMN_TYPES: dict[str, DatasetJsonDataType] = {
    "STUDYID": DatasetJsonDataType.STRING,
    "DOMAIN": DatasetJsonDataType.STRING,
    "USUBJID": DatasetJsonDataType.STRING,
    "AESEQ": DatasetJsonDataType.INTEGER,
    "AETERM": DatasetJsonDataType.STRING,
    "AEDECOD": DatasetJsonDataType.STRING,
    "AESEV": DatasetJsonDataType.STRING,
    "AESER": DatasetJsonDataType.STRING,
    "AESTDTC": DatasetJsonDataType.DATE,
    "AEENDTC": DatasetJsonDataType.DATE,
}


class AdverseEventSeverity(StrEnum):
    """Source severity categories; these are not CTCAE toxicity grades."""

    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class AdverseEventImportErrorCode(StrEnum):
    """Stable reasons that an AE document cannot be normalized."""

    WRONG_DOMAIN = "WRONG_DOMAIN"
    MISSING_REQUIRED_COLUMNS = "MISSING_REQUIRED_COLUMNS"
    COLUMN_TYPE_MISMATCH = "COLUMN_TYPE_MISMATCH"
    INVALID_RECORD = "INVALID_RECORD"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"


class AdverseEventImportError(ValueError):
    """Raised when an AE document violates its domain-specific contract."""

    def __init__(
        self,
        code: AdverseEventImportErrorCode,
        message: str,
        *,
        record_number: int | None = None,
        fields: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.record_number = record_number
        self.fields = fields


class AdverseEvent(BaseModel):
    """One typed AE row with its source identity and unmodified date strings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_number: int = Field(ge=1)
    study_id: StrictNonEmptyString
    unique_subject_id: StrictNonEmptyString
    event_sequence: PositiveSequence
    reported_term: StrictNonEmptyString
    preferred_term: StrictNonEmptyString
    severity: AdverseEventSeverity
    serious_flag: Literal["Y", "N"]
    start_date_text: StrictNonEmptyString
    end_date_text: StrictStr | None


def parse_adverse_events(document: DatasetJsonDocument) -> tuple[AdverseEvent, ...]:
    """Validate and normalize all AE rows without making clinical timing claims."""
    if document.name != "AE":
        raise AdverseEventImportError(
            AdverseEventImportErrorCode.WRONG_DOMAIN,
            f"Expected AE but received {document.name}.",
        )

    try:
        require_columns(document, AE_COLUMN_TYPES)
    except MissingRequiredColumnsError as exc:
        raise AdverseEventImportError(
            AdverseEventImportErrorCode.MISSING_REQUIRED_COLUMNS,
            str(exc),
            fields=exc.missing_columns,
        ) from exc

    columns_by_name = {column.name: column for column in document.columns}
    mismatched_types = tuple(
        sorted(
            name
            for name, expected_type in AE_COLUMN_TYPES.items()
            if columns_by_name[name].data_type is not expected_type
        )
    )
    if mismatched_types:
        raise AdverseEventImportError(
            AdverseEventImportErrorCode.COLUMN_TYPE_MISMATCH,
            f"AE columns have unexpected data types: {', '.join(mismatched_types)}",
            fields=mismatched_types,
        )

    events: list[AdverseEvent] = []
    event_keys: set[tuple[str, int]] = set()
    for row in iter_named_rows(document):
        if row.values["DOMAIN"] != "AE":
            raise AdverseEventImportError(
                AdverseEventImportErrorCode.INVALID_RECORD,
                "AE row has an unexpected DOMAIN value.",
                record_number=row.record_number,
                fields=("DOMAIN",),
            )
        if row.values["STUDYID"] != document.study_oid:
            raise AdverseEventImportError(
                AdverseEventImportErrorCode.INVALID_RECORD,
                "AE row STUDYID does not match the document study OID.",
                record_number=row.record_number,
                fields=("STUDYID",),
            )

        end_date = row.values["AEENDTC"]
        try:
            event = AdverseEvent.model_validate(
                {
                    "source_record_number": row.record_number,
                    "study_id": row.values["STUDYID"],
                    "unique_subject_id": row.values["USUBJID"],
                    "event_sequence": row.values["AESEQ"],
                    "reported_term": row.values["AETERM"],
                    "preferred_term": row.values["AEDECOD"],
                    "severity": row.values["AESEV"],
                    "serious_flag": row.values["AESER"],
                    "start_date_text": row.values["AESTDTC"],
                    "end_date_text": None if end_date == "" else end_date,
                }
            )
        except ValidationError as exc:
            fields = tuple(sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]}))
            raise AdverseEventImportError(
                AdverseEventImportErrorCode.INVALID_RECORD,
                "AE row contains invalid event values.",
                record_number=row.record_number,
                fields=fields,
            ) from exc

        event_key = (event.unique_subject_id, event.event_sequence)
        if event_key in event_keys:
            raise AdverseEventImportError(
                AdverseEventImportErrorCode.DUPLICATE_EVENT,
                "AE contains a duplicate USUBJID and AESEQ pair.",
                record_number=row.record_number,
                fields=("USUBJID", "AESEQ"),
            )

        event_keys.add(event_key)
        events.append(event)

    return tuple(events)
