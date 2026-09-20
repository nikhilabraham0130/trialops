"""Tests for deterministic planning with the fake model."""

import asyncio
from uuid import UUID, uuid4

import pytest

from trialops.agent.contracts import AnalysisPlan, ApprovedToolName, PlanStatus
from trialops.agent.fake_model import FakePlanModel
from trialops.agent.model import PlanModelError
from trialops.agent.orchestrator import (
    AgentPlanningError,
    AgentPlanningErrorCode,
    propose_analysis_plan,
)

VALID_RESPONSE = (
    '{"tool_name":"calculate_alt_gt_3x_uln",'
    '"purpose":"Use the approved ALT threshold calculation."}'
)


def _propose(
    model: FakePlanModel,
    *,
    question: str = "Were any ALT measurements above three times the upper limit?",
) -> tuple[AnalysisPlan, UUID, UUID]:
    dataset_version_id = uuid4()
    plan_id = uuid4()
    plan = asyncio.run(
        propose_analysis_plan(
            model,
            question=question,
            dataset_version_id=dataset_version_id,
            plan_id=plan_id,
        )
    )
    return plan, dataset_version_id, plan_id


def test_orchestrator_sends_only_question_and_approved_catalog_to_fake_model() -> None:
    model = FakePlanModel(VALID_RESPONSE)

    plan, dataset_version_id, plan_id = _propose(model)

    assert len(model.requests) == 1
    request = model.requests[0]
    assert request.question == "Were any ALT measurements above three times the upper limit?"
    assert len(request.tools) == 1
    assert request.tools[0].name is ApprovedToolName.CALCULATE_ALT_GT_3X_ULN
    assert request.tools[0].requires_confirmation
    assert plan.id == plan_id
    assert plan.dataset_version_id == dataset_version_id
    assert plan.tool_call.arguments.dataset_version_id == dataset_version_id
    assert plan.status is PlanStatus.AWAITING_CONFIRMATION


def test_orchestrator_does_not_execute_the_proposed_tool() -> None:
    model = FakePlanModel(VALID_RESPONSE)

    plan, _, _ = _propose(model)

    assert plan.confirmation_required
    assert plan.status is PlanStatus.AWAITING_CONFIRMATION


@pytest.mark.parametrize(
    "response_json",
    [
        "not json",
        '{"tool_name":"invented_tool","purpose":"Do something unsupported."}',
        '{"tool_name":"calculate_alt_gt_3x_uln"}',
        (
            '{"tool_name":"calculate_alt_gt_3x_uln","purpose":"Check ALT.",'
            '"dataset_version_id":"00000000-0000-0000-0000-000000000000"}'
        ),
    ],
)
def test_orchestrator_rejects_invalid_model_output(response_json: str) -> None:
    model = FakePlanModel(response_json)

    with pytest.raises(AgentPlanningError) as raised:
        _propose(model)

    assert raised.value.code is AgentPlanningErrorCode.INVALID_MODEL_RESPONSE
    assert "violates the approved contract" in str(raised.value)
    assert len(model.requests) == 1


def test_orchestrator_rejects_blank_question_before_calling_model() -> None:
    model = FakePlanModel(VALID_RESPONSE)

    with pytest.raises(AgentPlanningError) as raised:
        _propose(model, question="   ")

    assert raised.value.code is AgentPlanningErrorCode.INVALID_QUESTION
    assert model.requests == []


def test_orchestrator_translates_provider_failure_without_exposing_details() -> None:
    provider_error = PlanModelError("secret upstream failure details")
    model = FakePlanModel(VALID_RESPONSE, error=provider_error)

    with pytest.raises(AgentPlanningError) as raised:
        _propose(model)

    assert raised.value.code is AgentPlanningErrorCode.MODEL_UNAVAILABLE
    assert str(raised.value) == "The planning model is temporarily unavailable."
    assert "secret" not in str(raised.value)
    assert raised.value.__cause__ is provider_error
    assert len(model.requests) == 1
