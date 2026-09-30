"""Stable structured contracts for deterministic analytics results."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from trialops.analytics.lab_abnormalities import (
    AltAbnormalityResult,
    TimingClassification,
)
from trialops.analytics.severe_adverse_events import SevereAeIncidenceResult
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
