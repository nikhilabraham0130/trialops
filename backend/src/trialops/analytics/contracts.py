"""Stable structured contracts for deterministic analytics results."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from trialops.analytics.lab_abnormalities import (
    AltAbnormalityResult,
    TimingClassification,
)
from trialops.analytics.serious_adverse_events import SeriousAeIncidenceResult
from trialops.analytics.severe_adverse_events import SevereAeIncidenceResult
from trialops.analytics.subject_safety import SubjectSafetySummary
from trialops.validation.findings import FindingSeverity


class ValidationFindingResponse(BaseModel):
    """One machine-readable reason a source row was excluded or blocked."""

    rule_code: str
    severity: FindingSeverity
    domain: str
    source_record_number: int | None
    message: str


class AltExceedanceResponse(BaseModel):
    """Source evidence for one ALT result above three times its upper limit."""

    source_record_number: int
    unique_subject_id: str
    standard_result: Decimal
    upper_reference_limit: Decimal
    threshold: Decimal
    timing: TimingClassification


class AltAbnormalityResponse(BaseModel):
    """Structured output of one version-specific ALT threshold calculation."""

    dataset_version_id: UUID
    method_version: str
    threshold_multiplier: Decimal
    alt_row_count: int
    eligible_row_count: int
    excluded_row_count: int
    qualifying_measurement_count: int
    subjects_with_qualifying_measurement: int
    exceedances: tuple[AltExceedanceResponse, ...]
    findings: tuple[ValidationFindingResponse, ...]
    timing_limitation: str


def to_alt_abnormality_response(
    dataset_version_id: UUID, result: AltAbnormalityResult
) -> AltAbnormalityResponse:
    """Convert a domain calculation into its stable structured contract."""
    return AltAbnormalityResponse(
        dataset_version_id=dataset_version_id,
        method_version=result.method_version,
        threshold_multiplier=result.threshold_multiplier,
        alt_row_count=result.alt_row_count,
        eligible_row_count=result.eligible_row_count,
        excluded_row_count=result.excluded_row_count,
        qualifying_measurement_count=result.exceedance_count,
        subjects_with_qualifying_measurement=result.subjects_with_exceedance,
        exceedances=tuple(
            AltExceedanceResponse.model_validate(item, from_attributes=True)
            for item in result.exceedances
        ),
        findings=tuple(
            ValidationFindingResponse.model_validate(item, from_attributes=True)
            for item in result.findings
        ),
        timing_limitation=(
            "A blank baseline flag means not identified as baseline; it does not prove "
            "collection occurred after treatment began."
        ),
    )


class SevereAeArmResponse(BaseModel):
    """Distinct-subject incidence and event count for one actual treatment arm."""

    arm: str
    subjects_in_arm: int
    subjects_with_severe_ae: int
    severe_ae_event_count: int
    incidence_percent: Decimal


class SevereAeEvidenceResponse(BaseModel):
    """Source AE row supporting a severe-event count."""

    source_record_number: int
    unique_subject_id: str
    arm: str
    preferred_term: str


class SevereAeIncidenceResponse(BaseModel):
    """Versioned descriptive result, not a treatment-emergent comparison."""

    dataset_version_id: UUID
    method_version: str
    excluded_screen_failure_subjects: int
    population_definition: str
    timing_limitation: str
    arms: tuple[SevereAeArmResponse, ...]
    evidence: tuple[SevereAeEvidenceResponse, ...]


def to_severe_ae_incidence_response(
    dataset_version_id: UUID, result: SevereAeIncidenceResult
) -> SevereAeIncidenceResponse:
    """Expose the trusted counts with explicit population and timing limits."""
    return SevereAeIncidenceResponse(
        dataset_version_id=dataset_version_id,
        method_version=result.method_version,
        excluded_screen_failure_subjects=result.excluded_screen_failure_subjects,
        population_definition=(
            "DM subjects grouped by actual treatment arm (ACTARM), excluding ACTARM = "
            "Screen Failure; no safety-population flag or exposure requirement has been applied."
        ),
        timing_limitation=(
            "These are recorded severe AEs (AESEV = SEVERE), not confirmed "
            "treatment-emergent events. Severity is not the seriousness flag (AESER)."
        ),
        arms=tuple(
            SevereAeArmResponse.model_validate(arm, from_attributes=True) for arm in result.arms
        ),
        evidence=tuple(
            SevereAeEvidenceResponse.model_validate(item, from_attributes=True)
            for item in result.evidence
        ),
    )


class SeriousAeArmResponse(BaseModel):
    arm: str
    subjects_in_arm: int
    subjects_with_serious_ae: int
    serious_ae_event_count: int
    incidence_percent: Decimal


class SeriousAeEvidenceResponse(BaseModel):
    source_record_number: int
    unique_subject_id: str
    arm: str
    preferred_term: str


class SeriousAeIncidenceResponse(BaseModel):
    """Versioned descriptive seriousness result, separate from severity."""

    dataset_version_id: UUID
    method_version: str
    excluded_screen_failure_subjects: int
    population_definition: str
    timing_limitation: str
    arms: tuple[SeriousAeArmResponse, ...]
    evidence: tuple[SeriousAeEvidenceResponse, ...]


def to_serious_ae_incidence_response(
    dataset_version_id: UUID, result: SeriousAeIncidenceResult
) -> SeriousAeIncidenceResponse:
    return SeriousAeIncidenceResponse(
        dataset_version_id=dataset_version_id,
        method_version=result.method_version,
        excluded_screen_failure_subjects=result.excluded_screen_failure_subjects,
        population_definition=(
            "DM subjects grouped by actual treatment arm (ACTARM), excluding ACTARM = "
            "Screen Failure; no safety-population flag or exposure requirement has been applied."
        ),
        timing_limitation=(
            "These are recorded serious AEs (AESER = Y), not confirmed treatment-emergent "
            "events. Seriousness is separate from AE severity (AESEV)."
        ),
        arms=tuple(
            SeriousAeArmResponse.model_validate(arm, from_attributes=True) for arm in result.arms
        ),
        evidence=tuple(
            SeriousAeEvidenceResponse.model_validate(item, from_attributes=True)
            for item in result.evidence
        ),
    )


class SubjectSafetyEventResponse(BaseModel):
    source_record_number: int
    preferred_term: str
    severity: str
    serious_flag: str
    start_date_text: str


class SubjectFlaggedLabResponse(BaseModel):
    source_record_number: int
    test_code: str
    standard_result: Decimal | None
    standard_unit: str | None
    lower_reference_limit: Decimal | None
    upper_reference_limit: Decimal | None
    range_indicator: str
    baseline_flag: str | None
    observed_at_text: str


class SubjectSafetySummaryResponse(BaseModel):
    """Source-linked description, not a medical or treatment-emergent assessment."""

    dataset_version_id: UUID
    method_version: str
    unique_subject_id: str
    actual_arm: str
    age: int
    age_unit: str
    sex: str
    ae_event_count: int
    severe_ae_event_count: int
    serious_ae_event_count: int
    lab_result_count: int
    flagged_lab_count: int
    events: tuple[SubjectSafetyEventResponse, ...]
    flagged_labs: tuple[SubjectFlaggedLabResponse, ...]
    interpretation_limit: str


def to_subject_safety_summary_response(
    dataset_version_id: UUID, result: SubjectSafetySummary
) -> SubjectSafetySummaryResponse:
    """Make the source classification and timing limits explicit in the API."""
    return SubjectSafetySummaryResponse(
        dataset_version_id=dataset_version_id,
        method_version=result.method_version,
        unique_subject_id=result.unique_subject_id,
        actual_arm=result.actual_arm,
        age=result.age,
        age_unit=result.age_unit,
        sex=result.sex,
        ae_event_count=result.ae_event_count,
        severe_ae_event_count=result.severe_ae_event_count,
        serious_ae_event_count=result.serious_ae_event_count,
        lab_result_count=result.lab_result_count,
        flagged_lab_count=result.flagged_lab_count,
        events=tuple(
            SubjectSafetyEventResponse.model_validate(event, from_attributes=True)
            for event in result.events
        ),
        flagged_labs=tuple(
            SubjectFlaggedLabResponse.model_validate(lab, from_attributes=True)
            for lab in result.flagged_labs
        ),
        interpretation_limit=(
            "AE severity (AESEV) and seriousness (AESER) are distinct. Flagged labs use the "
            "source LBNRIND classification, not a derived clinical diagnosis. Event timing "
            "and treatment emergence have not been assessed."
        ),
    )
