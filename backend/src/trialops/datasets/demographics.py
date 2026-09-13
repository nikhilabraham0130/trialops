"""Domain-specific normalization for SDTM demographics data."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from trialops.datasets.dataset_json import DatasetJsonDataType, DatasetJsonDocument
from trialops.datasets.table import MissingRequiredColumnsError, iter_named_rows, require_columns

StrictNonEmptyString = Annotated[StrictStr, Field(min_length=1)]
SubjectAge = Annotated[StrictInt, Field(ge=0, le=130)]

DM_COLUMN_TYPES: dict[str, DatasetJsonDataType] = {
    "STUDYID": DatasetJsonDataType.STRING,
    "DOMAIN": DatasetJsonDataType.STRING,
    "USUBJID": DatasetJsonDataType.STRING,
    "SUBJID": DatasetJsonDataType.STRING,
    "AGE": DatasetJsonDataType.INTEGER,
    "AGEU": DatasetJsonDataType.STRING,
    "SEX": DatasetJsonDataType.STRING,
    "RACE": DatasetJsonDataType.STRING,
    "ARM": DatasetJsonDataType.STRING,
    "ACTARM": DatasetJsonDataType.STRING,
}


class DemographicsImportErrorCode(StrEnum):
    """Stable reasons that a demographics document cannot be normalized."""

    WRONG_DOMAIN = "WRONG_DOMAIN"
    MISSING_REQUIRED_COLUMNS = "MISSING_REQUIRED_COLUMNS"
    COLUMN_TYPE_MISMATCH = "COLUMN_TYPE_MISMATCH"
    INVALID_RECORD = "INVALID_RECORD"
    DUPLICATE_SUBJECT = "DUPLICATE_SUBJECT"


class DemographicsImportError(ValueError):
    """Raised when a DM document violates its domain-specific contract."""

    def __init__(
        self,
        code: DemographicsImportErrorCode,
        message: str,
        *,
        record_number: int | None = None,
        fields: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.record_number = record_number
        self.fields = fields


class DemographicsSubject(BaseModel):
    """Normalized subject fields required by the initial TrialOps workflows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_number: int = Field(ge=1)
    study_id: StrictNonEmptyString
    unique_subject_id: StrictNonEmptyString
    subject_id: StrictNonEmptyString
    age: SubjectAge
    age_unit: StrictNonEmptyString
    sex: StrictNonEmptyString
    race: StrictNonEmptyString
    planned_arm: StrictNonEmptyString
    actual_arm: StrictNonEmptyString


def parse_demographics_subjects(
    document: DatasetJsonDocument,
) -> tuple[DemographicsSubject, ...]:
    """Validate and normalize all subject rows from one DM document."""
    if document.name != "DM":
        raise DemographicsImportError(
            DemographicsImportErrorCode.WRONG_DOMAIN,
            f"Expected DM but received {document.name}.",
        )

    try:
        require_columns(document, DM_COLUMN_TYPES)
    except MissingRequiredColumnsError as exc:
        raise DemographicsImportError(
            DemographicsImportErrorCode.MISSING_REQUIRED_COLUMNS,
            str(exc),
            fields=exc.missing_columns,
        ) from exc

    columns_by_name = {column.name: column for column in document.columns}
    mismatched_types = tuple(
        sorted(
            name
            for name, expected_type in DM_COLUMN_TYPES.items()
            if columns_by_name[name].data_type is not expected_type
        )
    )
    if mismatched_types:
        raise DemographicsImportError(
            DemographicsImportErrorCode.COLUMN_TYPE_MISMATCH,
            f"DM columns have unexpected data types: {', '.join(mismatched_types)}",
            fields=mismatched_types,
        )

    subjects: list[DemographicsSubject] = []
    subject_ids: set[str] = set()
    for row in iter_named_rows(document):
        if row.values["DOMAIN"] != "DM":
            raise DemographicsImportError(
                DemographicsImportErrorCode.INVALID_RECORD,
                "DM row has an unexpected DOMAIN value.",
                record_number=row.record_number,
                fields=("DOMAIN",),
            )
        if row.values["STUDYID"] != document.study_oid:
            raise DemographicsImportError(
                DemographicsImportErrorCode.INVALID_RECORD,
                "DM row STUDYID does not match the document study OID.",
                record_number=row.record_number,
                fields=("STUDYID",),
            )

        try:
            subject = DemographicsSubject.model_validate(
                {
                    "source_record_number": row.record_number,
                    "study_id": row.values["STUDYID"],
                    "unique_subject_id": row.values["USUBJID"],
                    "subject_id": row.values["SUBJID"],
                    "age": row.values["AGE"],
                    "age_unit": row.values["AGEU"],
                    "sex": row.values["SEX"],
                    "race": row.values["RACE"],
                    "planned_arm": row.values["ARM"],
                    "actual_arm": row.values["ACTARM"],
                }
            )
        except ValidationError as exc:
            fields = tuple(sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]}))
            raise DemographicsImportError(
                DemographicsImportErrorCode.INVALID_RECORD,
                "DM row contains invalid subject values.",
                record_number=row.record_number,
                fields=fields,
            ) from exc

        if subject.unique_subject_id in subject_ids:
            raise DemographicsImportError(
                DemographicsImportErrorCode.DUPLICATE_SUBJECT,
                f"DM contains a duplicate USUBJID: {subject.unique_subject_id}",
                record_number=row.record_number,
                fields=("USUBJID",),
            )

        subject_ids.add(subject.unique_subject_id)
        subjects.append(subject)

    return tuple(subjects)
