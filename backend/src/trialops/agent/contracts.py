"""Typed contracts between a language model and trusted application code."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trialops.analytics.contracts import AltAbnormalityResponse

NonEmptyText = Annotated[str, Field(min_length=1)]


class ApprovedToolName(StrEnum):
    """Tool names the current agent is permitted to request."""

    CALCULATE_ALT_GT_3X_ULN = "calculate_alt_gt_3x_uln"


class PlanStatus(StrEnum):
    """Controlled lifecycle states for a proposed tool call."""

    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class ModelPlanProposal(BaseModel):
    """Small observable proposal a model must return instead of free-form actions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: ApprovedToolName
    purpose: NonEmptyText

    @field_validator("purpose")
    @classmethod
    def reject_blank_purpose(cls, value: str) -> str:
        """Reject explanations that contain only whitespace."""
        if not value.strip():
            raise ValueError("purpose must contain visible text")
        return value


class AltThresholdToolInput(BaseModel):
    """Application-controlled inputs for the approved ALT calculation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version_id: UUID


class ApprovedToolCall(BaseModel):
    """One validated tool request embedded in a user-visible plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal[ApprovedToolName.CALCULATE_ALT_GT_3X_ULN]
    arguments: AltThresholdToolInput


class AnalysisPlan(BaseModel):
    """Immutable plan that must be confirmed before its tool can run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    question: NonEmptyText
    dataset_version_id: UUID
    purpose: NonEmptyText
    status: Literal[PlanStatus.AWAITING_CONFIRMATION]
    confirmation_required: Literal[True]
    tool_call: ApprovedToolCall


class AnalysisExecution(BaseModel):
    """Persisted deterministic result returned after explicit confirmation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: UUID
    status: Literal[PlanStatus.EXECUTED]
    tool_name: Literal[ApprovedToolName.CALCULATE_ALT_GT_3X_ULN]
    result: AltAbnormalityResponse


class AnalysisPlanDetails(BaseModel):
    """Complete server-controlled state returned when a saved plan is loaded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    question: NonEmptyText
    dataset_version_id: UUID
    purpose: NonEmptyText
    status: PlanStatus
    confirmation_required: bool
    tool_call: ApprovedToolCall
    result: AltAbnormalityResponse | None
    created_at: datetime
    executed_at: datetime | None

    @field_validator("question", "purpose")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Require visible text when rebuilding persisted plan details."""
        if not value.strip():
            raise ValueError("stored plan text must contain visible text")
        return value


def create_analysis_plan(
    *,
    question: str,
    dataset_version_id: UUID,
    proposal: ModelPlanProposal,
    plan_id: UUID | None = None,
) -> AnalysisPlan:
    """Bind a model proposal to the version selected by trusted application code."""
    if not question.strip():
        raise ValueError("question must contain visible text")

    tool_call = ApprovedToolCall(
        name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
        arguments=AltThresholdToolInput(dataset_version_id=dataset_version_id),
    )
    return AnalysisPlan(
        id=plan_id or uuid4(),
        question=question,
        dataset_version_id=dataset_version_id,
        purpose=proposal.purpose,
        status=PlanStatus.AWAITING_CONFIRMATION,
        confirmation_required=True,
        tool_call=tool_call,
    )
