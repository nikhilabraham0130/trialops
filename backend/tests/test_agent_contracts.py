"""Tests for the AI plan contract and least-privilege tool catalog."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from trialops.agent.contracts import (
    AnalysisPlan,
    ApprovedToolName,
    ModelPlanProposal,
    PlanStatus,
    create_analysis_plan,
)
from trialops.agent.tools import get_approved_tool_specifications


def test_catalog_exposes_only_the_implemented_alt_tool() -> None:
    specifications = get_approved_tool_specifications()

    assert len(specifications) == 1
    specification = specifications[0]
    assert specification.name is ApprovedToolName.CALCULATE_ALT_GT_3X_ULN
    assert specification.requires_confirmation
    assert "strictly above" in specification.description
    assert "post-baseline" in specification.description
    assert specification.input_schema["required"] == ["dataset_version_id"]
    assert specification.input_schema["properties"]["dataset_version_id"]["format"] == "uuid"
    assert specification.input_schema["additionalProperties"] is False


def test_model_proposal_parses_only_a_known_tool_and_visible_purpose() -> None:
    proposal = ModelPlanProposal.model_validate_json(
        '{"tool_name":"calculate_alt_gt_3x_uln","purpose":"Check ALT threshold results."}'
    )

    assert proposal.tool_name is ApprovedToolName.CALCULATE_ALT_GT_3X_ULN
    assert proposal.purpose == "Check ALT threshold results."


@pytest.mark.parametrize(
    "payload",
    [
        '{"tool_name":"run_arbitrary_sql","purpose":"Query everything."}',
        '{"tool_name":"calculate_alt_gt_3x_uln","purpose":"   "}',
        (
            '{"tool_name":"calculate_alt_gt_3x_uln","purpose":"Check ALT.",'
            '"dataset_version_id":"00000000-0000-0000-0000-000000000000"}'
        ),
    ],
)
def test_model_proposal_rejects_unknown_tools_blank_purpose_and_extra_fields(payload: str) -> None:
    with pytest.raises(ValidationError):
        ModelPlanProposal.model_validate_json(payload)


def test_application_binds_plan_to_its_selected_dataset_version() -> None:
    dataset_version_id = uuid4()
    plan_id = uuid4()
    proposal = ModelPlanProposal(
        tool_name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
        purpose="Use the approved ALT threshold method.",
    )

    plan = create_analysis_plan(
        question="Were any ALT measurements greater than three times the upper limit?",
        dataset_version_id=dataset_version_id,
        proposal=proposal,
        plan_id=plan_id,
    )

    assert plan.id == plan_id
    assert plan.dataset_version_id == dataset_version_id
    assert plan.tool_call.arguments.dataset_version_id == dataset_version_id
    assert plan.tool_call.name is ApprovedToolName.CALCULATE_ALT_GT_3X_ULN
    assert plan.status is PlanStatus.AWAITING_CONFIRMATION
    assert plan.confirmation_required is True


def test_plan_generates_identity_when_application_does_not_supply_one() -> None:
    plan = create_analysis_plan(
        question="Check ALT.",
        dataset_version_id=uuid4(),
        proposal=ModelPlanProposal(
            tool_name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
            purpose="Use the approved method.",
        ),
    )

    assert plan.id.version == 4


def test_plan_rejects_blank_question() -> None:
    with pytest.raises(ValueError, match="question must contain visible text"):
        create_analysis_plan(
            question="  ",
            dataset_version_id=uuid4(),
            proposal=ModelPlanProposal(
                tool_name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
                purpose="Use the approved method.",
            ),
        )


def test_plan_is_immutable_after_creation() -> None:
    plan = create_analysis_plan(
        question="Check ALT.",
        dataset_version_id=uuid4(),
        proposal=ModelPlanProposal(
            tool_name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
            purpose="Use the approved method.",
        ),
    )

    with pytest.raises(ValidationError):
        plan.status = PlanStatus.AWAITING_CONFIRMATION

    assert isinstance(plan, AnalysisPlan)
