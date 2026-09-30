"""Tests for deterministic planning with the fake model."""

import asyncio
from uuid import UUID, uuid4

import pytest

from trialops.agent.contracts import (
    AnalysisPlan,
    ApprovedToolName,
    PlanStatus,
    SubjectSafetyToolInput,
)
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
    assert len(request.tools) == 3
    assert request.tools[0].name is ApprovedToolName.CALCULATE_ALT_GT_3X_ULN
    assert request.tools[0].requires_confirmation
    assert request.tools[1].name is ApprovedToolName.COMPARE_SEVERE_AE_INCIDENCE
    assert request.tools[2].name is ApprovedToolName.GET_SUBJECT_SAFETY_SUMMARY
    assert plan.id == plan_id
    assert plan.dataset_version_id == dataset_version_id
    assert plan.tool_call.arguments.dataset_version_id == dataset_version_id
    assert plan.status is PlanStatus.AWAITING_CONFIRMATION


def test_orchestrator_does_not_execute_the_proposed_tool() -> None:
    model = FakePlanModel(VALID_RESPONSE)

    plan, _, _ = _propose(model)

    assert plan.confirmation_required
    assert plan.status is PlanStatus.AWAITING_CONFIRMATION


def test_orchestrator_can_select_severe_ae_tool_without_executing_it() -> None:
    model = FakePlanModel(
        '{"tool_name":"compare_severe_ae_incidence",'
        '"purpose":"Count subjects with recorded severe AEs by actual arm."}'
    )

    plan, dataset_version_id, _ = _propose(
        model, question="Which treatment arm had recorded severe AEs?"
    )

    assert plan.tool_call.name is ApprovedToolName.COMPARE_SEVERE_AE_INCIDENCE
    assert plan.tool_call.arguments.dataset_version_id == dataset_version_id
    assert plan.status is PlanStatus.AWAITING_CONFIRMATION


def test_orchestrator_can_select_an_explicitly_named_subject() -> None:
    model = FakePlanModel(
        '{"tool_name":"get_subject_safety_summary","purpose":"Show source records.",'
        '"subject_id":"S1"}'
    )
    plan, _, _ = _propose(model, question="Summarize subject S1.")
    assert plan.tool_call.name is ApprovedToolName.GET_SUBJECT_SAFETY_SUMMARY
    assert isinstance(plan.tool_call.arguments, SubjectSafetyToolInput)
    assert plan.tool_call.arguments.subject_id == "S1"


@pytest.mark.parametrize(
    ("response", "question"),
    [
        (
            '{"tool_name":"get_subject_safety_summary","purpose":"Show source records."}',
            "Summarize subject S1.",
        ),
        (
            '{"tool_name":"get_subject_safety_summary","purpose":"Show source records.",'
            '"subject_id":"S2"}',
            "Summarize subject S1.",
        ),
        (
            '{"tool_name":"calculate_alt_gt_3x_uln","purpose":"Check ALT.","subject_id":"S1"}',
            "Check ALT for S1.",
        ),
    ],
)
def test_orchestrator_rejects_missing_invented_or_unexpected_subject_ids(
    response: str, question: str
) -> None:
    with pytest.raises(AgentPlanningError) as raised:
        _propose(FakePlanModel(response), question=question)
    assert raised.value.code is AgentPlanningErrorCode.INVALID_MODEL_RESPONSE


def test_orchestrator_refuses_a_question_outside_the_tool_catalog() -> None:
    model = FakePlanModel('{"tool_name":"unsupported","purpose":"CTCAE grade is not available."}')

    with pytest.raises(AgentPlanningError) as raised:
        _propose(model, question="Which subjects had Grade 3 events?")

    assert raised.value.code is AgentPlanningErrorCode.ANALYSIS_NOT_SUPPORTED


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
