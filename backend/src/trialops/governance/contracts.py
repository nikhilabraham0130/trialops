"""Typed outputs produced by deterministic governance policies."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class PolicyCode(StrEnum):
    """Stable identifiers for the first analysis governance rules."""

    DETERMINISTIC_RESULT_REQUIRED = "DETERMINISTIC_RESULT_REQUIRED"
    NUMERIC_GROUNDING_REQUIRED = "NUMERIC_GROUNDING_REQUIRED"
    INDEPENDENT_REVIEW_REQUIRED = "INDEPENDENT_REVIEW_REQUIRED"


class PolicyStatus(StrEnum):
    """Whether one governance requirement is currently satisfied."""

    PASS = "PASS"
    FAIL = "FAIL"


class GovernanceDecision(StrEnum):
    """The next permitted governance state for an analysis."""

    NOT_READY_FOR_REVIEW = "NOT_READY_FOR_REVIEW"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class GovernanceFinding(BaseModel):
    """One explainable policy result rather than a hidden boolean decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_code: PolicyCode
    status: PolicyStatus
    blocking: bool
    message: str


class GovernanceEvaluation(BaseModel):
    """Combined governance decision and all rules that contributed to it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: GovernanceDecision
    findings: tuple[GovernanceFinding, ...]
