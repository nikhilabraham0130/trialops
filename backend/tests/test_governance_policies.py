"""Tests for deterministic analysis governance decisions."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from trialops.agent.contracts import (
    AltThresholdToolInput,
    AnalysisPlanDetails,
    ApprovedToolCall,
    ApprovedToolName,
    PlanStatus,
)
from trialops.agent.interpretation_contracts import GroundingStatus, StoredInterpretation
from trialops.analytics.contracts import AltAbnormalityResponse
from trialops.governance.contracts import (
    GovernanceDecision,
    GovernanceEvaluation,
    PolicyCode,
    PolicyStatus,
)
from trialops.governance.policies import evaluate_analysis_governance


def _plan(
    status: PlanStatus,
    *,
    with_interpretation: bool = False,
) -> AnalysisPlanDetails:
    version_id = uuid4()
    result = (
        AltAbnormalityResponse(
            dataset_version_id=version_id,
            method_version="alt-gt-3x-uln/1.0",
            threshold_multiplier=Decimal(3),
            alt_row_count=10,
            eligible_row_count=8,
            excluded_row_count=2,
            qualifying_measurement_count=1,
            subjects_with_qualifying_measurement=1,
            exceedances=(),
            findings=(),
            timing_limitation="Treatment timing has not yet been established.",
        )
        if status is PlanStatus.EXECUTED
        else None
    )
    interpretation = (
        StoredInterpretation(
            summary="One qualifying measurement was found.",
            numeric_claims=(),
            grounding_status=GroundingStatus.NUMERICALLY_VERIFIED,
            prompt_version="alt-result-interpretation/1.0",
            model_id="fake-model-v1",
            generated_at=datetime(2026, 9, 27, 12, 2, tzinfo=UTC),
        )
        if with_interpretation
        else None
    )
    return AnalysisPlanDetails(
        id=uuid4(),
        question="Were any ALT measurements above three times ULN?",
        dataset_version_id=version_id,
        purpose="Use the approved deterministic ALT calculation.",
        status=status,
        confirmation_required=status is PlanStatus.AWAITING_CONFIRMATION,
        tool_call=ApprovedToolCall(
            name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
            arguments=AltThresholdToolInput(dataset_version_id=version_id),
        ),
        result=result,
        interpretation=interpretation,
        created_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
        executed_at=(
            datetime(2026, 9, 27, 12, 1, tzinfo=UTC) if status is PlanStatus.EXECUTED else None
        ),
    )


def _finding_statuses(evaluation: GovernanceEvaluation) -> dict[PolicyCode, PolicyStatus]:
    return {finding.policy_code: finding.status for finding in evaluation.findings}


def test_executed_grounded_analysis_requires_independent_review() -> None:
    evaluation = evaluate_analysis_governance(_plan(PlanStatus.EXECUTED, with_interpretation=True))

    assert evaluation.decision is GovernanceDecision.REVIEW_REQUIRED
    assert _finding_statuses(evaluation) == {
        PolicyCode.DETERMINISTIC_RESULT_REQUIRED: PolicyStatus.PASS,
        PolicyCode.NUMERIC_GROUNDING_REQUIRED: PolicyStatus.PASS,
        PolicyCode.INDEPENDENT_REVIEW_REQUIRED: PolicyStatus.FAIL,
    }
    assert evaluation.findings[-1].blocking is True
    assert evaluation.findings[-1].message == "Independent reviewer approval is required."


def test_unexecuted_analysis_is_not_ready_for_review() -> None:
    evaluation = evaluate_analysis_governance(_plan(PlanStatus.AWAITING_CONFIRMATION))

    assert evaluation.decision is GovernanceDecision.NOT_READY_FOR_REVIEW
    assert _finding_statuses(evaluation) == {
        PolicyCode.DETERMINISTIC_RESULT_REQUIRED: PolicyStatus.FAIL,
        PolicyCode.NUMERIC_GROUNDING_REQUIRED: PolicyStatus.FAIL,
        PolicyCode.INDEPENDENT_REVIEW_REQUIRED: PolicyStatus.FAIL,
    }
    assert all(finding.blocking for finding in evaluation.findings)


def test_executed_analysis_without_grounded_interpretation_is_not_ready() -> None:
    evaluation = evaluate_analysis_governance(_plan(PlanStatus.EXECUTED))

    assert evaluation.decision is GovernanceDecision.NOT_READY_FOR_REVIEW
    statuses = _finding_statuses(evaluation)
    assert statuses[PolicyCode.DETERMINISTIC_RESULT_REQUIRED] is PolicyStatus.PASS
    assert statuses[PolicyCode.NUMERIC_GROUNDING_REQUIRED] is PolicyStatus.FAIL
    assert evaluation.findings[-1].message == (
        "Independent review cannot begin until the prerequisite checks pass."
    )
