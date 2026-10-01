"""Typed contracts between a language model and trusted application code."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trialops.agent.interpretation_contracts import StoredInterpretation
from trialops.analytics.contracts import (
    AltAbnormalityResponse,
    LabRangeResponse,
    SeriousAeIncidenceResponse,
    SevereAeIncidenceResponse,
    SubjectSafetySummaryResponse,
)
from trialops.reviews.contracts import ReviewState

NonEmptyText = Annotated[str, Field(min_length=1)]


class ApprovedToolName(StrEnum):
    """Tool names the current agent is permitted to request."""

    CALCULATE_ALT_GT_3X_ULN = "calculate_alt_gt_3x_uln"
    CHECK_LAB_REFERENCE_RANGE = "check_lab_reference_range"
    COMPARE_SEVERE_AE_INCIDENCE = "compare_severe_ae_incidence"
    COMPARE_SERIOUS_AE_INCIDENCE = "compare_serious_ae_incidence"
    GET_SUBJECT_SAFETY_SUMMARY = "get_subject_safety_summary"


class PlanStatus(StrEnum):
    """Controlled lifecycle states for a proposed tool call."""

    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class ModelPlanProposal(BaseModel):
    """Small observable proposal a model must return instead of free-form actions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: ApprovedToolName | Literal["unsupported"]
    purpose: NonEmptyText
    subject_id: str | None = Field(default=None, min_length=1, max_length=255)
    lab_test_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9]{1,7}$")

    @field_validator("purpose")
    @classmethod
    def reject_blank_purpose(cls, value: str) -> str:
        """Reject explanations that contain only whitespace."""
        if not value.strip():
            raise ValueError("purpose must contain visible text")
        return value

    @field_validator("subject_id")
    @classmethod
    def normalize_subject_id(cls, value: str | None) -> str | None:
        """Prevent whitespace-only subject identifiers in model proposals."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("subject_id must contain visible text")
        return normalized


class AltThresholdToolInput(BaseModel):
    """Application-controlled inputs for the approved ALT calculation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version_id: UUID


class LabRangeToolInput(BaseModel):
    """Exact LBTESTCD selected from the user's visible question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version_id: UUID
    test_code: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")


def question_mentions_lab_test(question: str, test_code: str) -> bool:
    return (
        re.search(
            rf"(?<![A-Za-z0-9]){re.escape(test_code)}(?![A-Za-z0-9])",
            question,
            flags=re.IGNORECASE,
        )
        is not None
    )


class SubjectSafetyToolInput(BaseModel):
    """Model-selected subject, bound to an application-selected dataset version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version_id: UUID
    subject_id: NonEmptyText


class ApprovedToolCall(BaseModel):
    """One validated tool request embedded in a user-visible plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: ApprovedToolName
    arguments: AltThresholdToolInput | LabRangeToolInput | SubjectSafetyToolInput


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
    tool_name: ApprovedToolName
    result: (
        AltAbnormalityResponse
        | LabRangeResponse
        | SevereAeIncidenceResponse
        | SeriousAeIncidenceResponse
        | SubjectSafetySummaryResponse
    )


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
    result: (
        AltAbnormalityResponse
        | LabRangeResponse
        | SevereAeIncidenceResponse
        | SeriousAeIncidenceResponse
        | SubjectSafetySummaryResponse
        | None
    )
    interpretation: StoredInterpretation | None
    created_at: datetime
    executed_at: datetime | None
    review_state: ReviewState = ReviewState.DRAFT
    submitted_by: str | None = None
    submitted_at: datetime | None = None

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
    tool_name = proposal.tool_name
    if not isinstance(tool_name, ApprovedToolName):
        raise ValueError("an unsupported question cannot create an executable plan")

    if tool_name is ApprovedToolName.GET_SUBJECT_SAFETY_SUMMARY:
        if proposal.subject_id is None or proposal.lab_test_code is not None:
            raise ValueError("a subject safety plan requires a subject_id")
        arguments: AltThresholdToolInput | LabRangeToolInput | SubjectSafetyToolInput = (
            SubjectSafetyToolInput(
                dataset_version_id=dataset_version_id,
                subject_id=proposal.subject_id,
            )
        )
    elif tool_name is ApprovedToolName.CHECK_LAB_REFERENCE_RANGE:
        if (
            proposal.subject_id is not None
            or proposal.lab_test_code is None
            or not question_mentions_lab_test(question, proposal.lab_test_code)
        ):
            raise ValueError("the lab test code must appear in the question")
        arguments = LabRangeToolInput(
            dataset_version_id=dataset_version_id,
            test_code=proposal.lab_test_code,
        )
    else:
        if proposal.subject_id is not None or proposal.lab_test_code is not None:
            raise ValueError("a non-subject tool cannot receive a subject_id or lab_test_code")
        arguments = AltThresholdToolInput(dataset_version_id=dataset_version_id)
    tool_call = ApprovedToolCall(name=tool_name, arguments=arguments)
    return AnalysisPlan(
        id=plan_id or uuid4(),
        question=question,
        dataset_version_id=dataset_version_id,
        purpose=proposal.purpose,
        status=PlanStatus.AWAITING_CONFIRMATION,
        confirmation_required=True,
        tool_call=tool_call,
    )
