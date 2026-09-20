"""Application-controlled conversion of questions into governed plans."""

from enum import StrEnum
from uuid import UUID

from pydantic import ValidationError

from trialops.agent.contracts import AnalysisPlan, ModelPlanProposal, create_analysis_plan
from trialops.agent.model import PlanModel, PlanModelError, PlanModelRequest
from trialops.agent.tools import get_approved_tool_specifications


class AgentPlanningErrorCode(StrEnum):
    """Stable reasons the application could not create an analysis plan."""

    INVALID_QUESTION = "INVALID_QUESTION"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    INVALID_MODEL_RESPONSE = "INVALID_MODEL_RESPONSE"


class AgentPlanningError(ValueError):
    """Safe planning failure that does not expose provider output or internals."""

    def __init__(self, code: AgentPlanningErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


async def propose_analysis_plan(
    model: PlanModel,
    *,
    question: str,
    dataset_version_id: UUID,
    plan_id: UUID | None = None,
) -> AnalysisPlan:
    """Ask a model for a proposal, validate it, and bind trusted application data."""
    if not question.strip():
        raise AgentPlanningError(
            AgentPlanningErrorCode.INVALID_QUESTION,
            "The analysis question must contain visible text.",
        )

    request = PlanModelRequest(
        question=question,
        tools=get_approved_tool_specifications(),
    )
    try:
        response_json = await model.generate_plan_json(request)
    except PlanModelError as exc:
        raise AgentPlanningError(
            AgentPlanningErrorCode.MODEL_UNAVAILABLE,
            "The planning model is temporarily unavailable.",
        ) from exc

    try:
        proposal = ModelPlanProposal.model_validate_json(response_json)
    except ValidationError as exc:
        raise AgentPlanningError(
            AgentPlanningErrorCode.INVALID_MODEL_RESPONSE,
            "The planning model returned a response that violates the approved contract.",
        ) from exc

    return create_analysis_plan(
        question=question,
        dataset_version_id=dataset_version_id,
        proposal=proposal,
        plan_id=plan_id,
    )
