"""Deterministic governance evaluation for the current safety analysis."""

from trialops.agent.contracts import AnalysisPlanDetails, PlanStatus
from trialops.agent.interpretation_contracts import GroundingStatus
from trialops.governance.contracts import (
    GovernanceDecision,
    GovernanceEvaluation,
    GovernanceFinding,
    PolicyCode,
    PolicyStatus,
)
from trialops.reviews.contracts import ReviewState


def _finding(
    policy_code: PolicyCode,
    passed: bool,
    *,
    pass_message: str,
    fail_message: str,
) -> GovernanceFinding:
    """Build one consistently shaped result from a deterministic condition."""
    return GovernanceFinding(
        policy_code=policy_code,
        status=PolicyStatus.PASS if passed else PolicyStatus.FAIL,
        blocking=not passed,
        message=pass_message if passed else fail_message,
    )


def evaluate_analysis_governance(plan: AnalysisPlanDetails) -> GovernanceEvaluation:
    """Decide whether an analysis is ready to enter independent review."""
    result_available = plan.status is PlanStatus.EXECUTED and plan.result is not None
    interpretation_grounded = (
        plan.interpretation is not None
        and plan.interpretation.grounding_status is GroundingStatus.NUMERICALLY_VERIFIED
    )

    result_finding = _finding(
        PolicyCode.DETERMINISTIC_RESULT_REQUIRED,
        result_available,
        pass_message="The analysis has a stored deterministic result.",
        fail_message="A stored deterministic result is required before review.",
    )
    grounding_finding = _finding(
        PolicyCode.NUMERIC_GROUNDING_REQUIRED,
        interpretation_grounded,
        pass_message="The AI interpretation passed numeric grounding verification.",
        fail_message="A numerically verified AI interpretation is required before review.",
    )
    prerequisites_pass = result_available and interpretation_grounded
    approved = plan.review_state is ReviewState.APPROVED
    review_finding = GovernanceFinding(
        policy_code=PolicyCode.INDEPENDENT_REVIEW_REQUIRED,
        status=PolicyStatus.PASS if approved else PolicyStatus.FAIL,
        blocking=not approved,
        message=(
            "An independent reviewer approved this analysis."
            if approved
            else "Independent reviewer approval is required."
            if prerequisites_pass
            else "Independent review cannot begin until the prerequisite checks pass."
        ),
    )

    if plan.review_state is ReviewState.REJECTED:
        decision = GovernanceDecision.REJECTED
    elif plan.review_state is ReviewState.CHANGES_REQUESTED:
        decision = GovernanceDecision.CHANGES_REQUESTED
    elif approved and prerequisites_pass:
        decision = GovernanceDecision.APPROVED
    elif prerequisites_pass:
        decision = GovernanceDecision.REVIEW_REQUIRED
    else:
        decision = GovernanceDecision.NOT_READY_FOR_REVIEW

    return GovernanceEvaluation(
        decision=decision,
        findings=(result_finding, grounding_finding, review_finding),
    )
