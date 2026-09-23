"""Typed contracts for numerically grounded AI interpretations."""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NumericFactName(StrEnum):
    """Aggregate result fields an interpretation may cite numerically."""

    THRESHOLD_MULTIPLIER = "threshold_multiplier"
    ALT_ROW_COUNT = "alt_row_count"
    ELIGIBLE_ROW_COUNT = "eligible_row_count"
    EXCLUDED_ROW_COUNT = "excluded_row_count"
    QUALIFYING_MEASUREMENT_COUNT = "qualifying_measurement_count"
    SUBJECTS_WITH_QUALIFYING_MEASUREMENT = "subjects_with_qualifying_measurement"


class GroundingStatus(StrEnum):
    """What the deterministic verifier established about an interpretation."""

    NUMERICALLY_VERIFIED = "NUMERICALLY_VERIFIED"


class NumericFact(BaseModel):
    """One trusted numeric value supplied to the interpretation model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NumericFactName
    value: Decimal


class NumericClaim(BaseModel):
    """One result field and value the model says it used in its summary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: NumericFactName
    value: Decimal


VisibleSummary = Annotated[str, Field(min_length=1, max_length=4000)]


class InterpretationProposal(BaseModel):
    """Strict JSON shape a model must return before grounding verification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: VisibleSummary
    numeric_claims: tuple[NumericClaim, ...]

    @field_validator("summary")
    @classmethod
    def require_visible_summary(cls, value: str) -> str:
        """Reject an explanation containing only whitespace."""
        if not value.strip():
            raise ValueError("summary must contain visible text")
        return value

    @model_validator(mode="after")
    def require_unique_claim_fields(self) -> "InterpretationProposal":
        """Prevent one field from being declared with conflicting values."""
        fields = [claim.field for claim in self.numeric_claims]
        if len(fields) != len(set(fields)):
            raise ValueError("numeric claim fields must be unique")
        return self


class VerifiedInterpretation(BaseModel):
    """AI explanation accepted by deterministic numeric grounding checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: VisibleSummary
    numeric_claims: tuple[NumericClaim, ...]
    grounding_status: Literal[GroundingStatus.NUMERICALLY_VERIFIED]
    prompt_version: str
    model_id: str
