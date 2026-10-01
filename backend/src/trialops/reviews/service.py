"""Atomic, independently authorized review transitions for saved analyses."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.models import AgentPlanRecord
from trialops.agent.queries import AgentPlanQueryError, validate_analysis_plan_record
from trialops.governance.contracts import GovernanceDecision
from trialops.governance.policies import evaluate_analysis_governance
from trialops.reviews.auth import ReviewActor, ReviewRole
from trialops.reviews.contracts import ReviewAction, ReviewEvent, ReviewState, ReviewStatus
from trialops.reviews.models import AuditEventRecord, ReviewEventRecord


class ReviewErrorCode(StrEnum):
    PLAN_NOT_FOUND = "PLAN_NOT_FOUND"
    REVIEW_NOT_READY = "REVIEW_NOT_READY"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    REVIEWER_CONFLICT = "REVIEWER_CONFLICT"
    ROLE_NOT_PERMITTED = "ROLE_NOT_PERMITTED"
    COMMENT_REQUIRED = "COMMENT_REQUIRED"


class ReviewError(RuntimeError):
    def __init__(self, code: ReviewErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def _require_role(actor: ReviewActor, role: ReviewRole) -> None:
    if actor.role is not role:
        raise ReviewError(
            ReviewErrorCode.ROLE_NOT_PERMITTED,
            f"Only a {role.value.lower()} may perform this action.",
        )


async def _locked_plan(session: AsyncSession, plan_id: UUID) -> AgentPlanRecord:
    record = await session.scalar(
        select(AgentPlanRecord).where(AgentPlanRecord.id == plan_id).with_for_update()
    )
    if record is None:
        raise ReviewError(
            ReviewErrorCode.PLAN_NOT_FOUND, "The requested analysis plan does not exist."
        )
    return record


def _append_event(
    session: AsyncSession,
    plan_id: UUID,
    actor: ReviewActor,
    action: ReviewAction,
    comment: str | None = None,
) -> None:
    """Write review and audit history in the same transaction as the state change."""
    session.add(
        ReviewEventRecord(
            id=uuid4(), plan_id=plan_id, action=action.value, actor_id=actor.id, comment=comment
        )
    )
    session.add(
        AuditEventRecord(
            id=uuid4(),
            actor_id=actor.id,
            action=f"REVIEW_{action.value}",
            entity_type="agent_plan",
            entity_id=plan_id,
            details={"review_action": action.value},
        )
    )


async def submit_analysis(session: AsyncSession, plan_id: UUID, actor: ReviewActor) -> ReviewStatus:
    """Submit only a completed, grounded analysis, never an unreviewed draft calculation."""
    _require_role(actor, ReviewRole.ANALYST)
    try:
        record = await _locked_plan(session, plan_id)
        if record.review_state != ReviewState.DRAFT:
            raise ReviewError(
                ReviewErrorCode.INVALID_STATE_TRANSITION,
                "Only a draft analysis may be submitted for review.",
            )
        try:
            details = validate_analysis_plan_record(record)
        except AgentPlanQueryError as exc:
            raise ReviewError(
                ReviewErrorCode.REVIEW_NOT_READY, "The saved analysis is not valid for review."
            ) from exc
        evaluation = evaluate_analysis_governance(details)
        if evaluation.decision is not GovernanceDecision.REVIEW_REQUIRED:
            raise ReviewError(
                ReviewErrorCode.REVIEW_NOT_READY,
                "A result and numerically verified interpretation are required before review.",
            )
        record.review_state = ReviewState.PENDING_REVIEW.value
        record.submitted_by = actor.id
        record.submitted_at = datetime.now(UTC)
        _append_event(session, plan_id, actor, ReviewAction.SUBMITTED)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_review_status(session, plan_id)


async def decide_review(
    session: AsyncSession,
    plan_id: UUID,
    actor: ReviewActor,
    action: ReviewAction,
    comment: str | None,
) -> ReviewStatus:
    """Make exactly one decision against a pending submission under a row lock."""
    _require_role(actor, ReviewRole.REVIEWER)
    if action is ReviewAction.SUBMITTED:
        raise ReviewError(
            ReviewErrorCode.INVALID_STATE_TRANSITION, "Submission is not a reviewer decision."
        )
    cleaned_comment = comment.strip() if comment is not None else None
    if action in {ReviewAction.REJECTED, ReviewAction.CHANGES_REQUESTED} and not cleaned_comment:
        raise ReviewError(
            ReviewErrorCode.COMMENT_REQUIRED, "A reason is required for this decision."
        )
    try:
        record = await _locked_plan(session, plan_id)
        if record.review_state != ReviewState.PENDING_REVIEW:
            raise ReviewError(
                ReviewErrorCode.INVALID_STATE_TRANSITION,
                "Only a pending analysis may receive a review decision.",
            )
        if record.submitted_by == actor.id:
            raise ReviewError(
                ReviewErrorCode.REVIEWER_CONFLICT,
                "A submitter cannot review their own analysis.",
            )
        if record.submitted_by is None:
            raise ReviewError(
                ReviewErrorCode.REVIEW_NOT_READY, "The pending analysis has no submitter."
            )
        record.review_state = ReviewState(action.value).value
        _append_event(session, plan_id, actor, action, cleaned_comment)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_review_status(session, plan_id)


async def get_review_status(session: AsyncSession, plan_id: UUID) -> ReviewStatus:
    """Read the current state plus the ordered, append-only decision history."""
    record = await session.scalar(select(AgentPlanRecord).where(AgentPlanRecord.id == plan_id))
    if record is None:
        raise ReviewError(
            ReviewErrorCode.PLAN_NOT_FOUND, "The requested analysis plan does not exist."
        )
    events = (
        await session.scalars(
            select(ReviewEventRecord)
            .where(ReviewEventRecord.plan_id == plan_id)
            .order_by(ReviewEventRecord.created_at, ReviewEventRecord.id)
        )
    ).all()
    return ReviewStatus(
        plan_id=plan_id,
        state=ReviewState(record.review_state),
        submitted_by=record.submitted_by,
        submitted_at=record.submitted_at,
        history=tuple(
            ReviewEvent(
                id=event.id,
                action=ReviewAction(event.action),
                actor_id=event.actor_id,
                comment=event.comment,
                created_at=event.created_at,
            )
            for event in events
        ),
    )
