"""Review transitions enforce role, grounding, and independent approval."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.contracts import PlanStatus
from trialops.agent.interpretation_contracts import GroundingStatus
from trialops.agent.models import AgentPlanRecord
from trialops.reviews.auth import ReviewActor, ReviewRole
from trialops.reviews.contracts import ReviewAction, ReviewState, ReviewStatus
from trialops.reviews.models import AuditEventRecord, ReviewEventRecord
from trialops.reviews.service import (
    ReviewError,
    ReviewErrorCode,
    decide_review,
    submit_analysis,
)


def _record(state: ReviewState = ReviewState.DRAFT) -> AgentPlanRecord:
    return AgentPlanRecord(
        id=uuid4(),
        review_state=state.value,
        submitted_by=None,
        submitted_at=None,
    )


def _saved_status(record: AgentPlanRecord) -> ReviewStatus:
    return ReviewStatus(
        plan_id=record.id,
        state=ReviewState(record.review_state),
        submitted_by=record.submitted_by,
        submitted_at=record.submitted_at,
        history=(),
    )


def test_analyst_can_submit_only_grounded_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    record = _record()
    session = AsyncMock(spec=AsyncSession)

    async def locked(_session: AsyncSession, _plan_id: object) -> AgentPlanRecord:
        return record

    async def status(_session: AsyncSession, _plan_id: object) -> ReviewStatus:
        return _saved_status(record)

    monkeypatch.setattr("trialops.reviews.service._locked_plan", locked)
    monkeypatch.setattr("trialops.reviews.service.get_review_status", status)
    monkeypatch.setattr(
        "trialops.reviews.service.validate_analysis_plan_record",
        lambda _record: SimpleNamespace(
            status=PlanStatus.EXECUTED,
            review_state=ReviewState.DRAFT,
            result=object(),
            interpretation=SimpleNamespace(grounding_status=GroundingStatus.NUMERICALLY_VERIFIED),
        ),
    )
    result = asyncio.run(
        submit_analysis(session, record.id, ReviewActor("local-analyst", ReviewRole.ANALYST))
    )
    assert result.state is ReviewState.PENDING_REVIEW
    assert result.submitted_by == "local-analyst"
    assert session.commit.await_count == 1
    added = [call.args[0] for call in session.add.call_args_list]
    assert any(isinstance(item, ReviewEventRecord) and item.action == "SUBMITTED" for item in added)
    assert any(
        isinstance(item, AuditEventRecord) and item.action == "REVIEW_SUBMITTED" for item in added
    )


def test_reviewer_cannot_submit_even_with_a_grounded_plan() -> None:
    session = AsyncMock(spec=AsyncSession)
    with pytest.raises(ReviewError) as failure:
        asyncio.run(submit_analysis(session, uuid4(), ReviewActor("reviewer", ReviewRole.REVIEWER)))
    assert failure.value.code is ReviewErrorCode.ROLE_NOT_PERMITTED
    assert session.scalar.await_count == 0


def test_submitter_cannot_review_own_pending_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    record = _record(ReviewState.PENDING_REVIEW)
    record.submitted_by = "same-person"
    record.submitted_at = datetime.now(UTC)
    session = AsyncMock(spec=AsyncSession)

    async def locked(_session: AsyncSession, _plan_id: object) -> AgentPlanRecord:
        return record

    monkeypatch.setattr("trialops.reviews.service._locked_plan", locked)
    with pytest.raises(ReviewError) as failure:
        asyncio.run(
            decide_review(
                session,
                record.id,
                ReviewActor("same-person", ReviewRole.REVIEWER),
                ReviewAction.APPROVED,
                None,
            )
        )
    assert failure.value.code is ReviewErrorCode.REVIEWER_CONFLICT
    assert session.commit.await_count == 0


def test_independent_reviewer_can_approve_once(monkeypatch: pytest.MonkeyPatch) -> None:
    record = _record(ReviewState.PENDING_REVIEW)
    record.submitted_by = "local-analyst"
    record.submitted_at = datetime.now(UTC)
    session = AsyncMock(spec=AsyncSession)

    async def locked(_session: AsyncSession, _plan_id: object) -> AgentPlanRecord:
        return record

    async def status(_session: AsyncSession, _plan_id: object) -> ReviewStatus:
        return _saved_status(record)

    monkeypatch.setattr("trialops.reviews.service._locked_plan", locked)
    monkeypatch.setattr("trialops.reviews.service.get_review_status", status)
    actor = ReviewActor("local-reviewer", ReviewRole.REVIEWER)
    result = asyncio.run(
        decide_review(session, record.id, actor, ReviewAction.APPROVED, "Checked.")
    )
    assert result.state is ReviewState.APPROVED
    assert session.commit.await_count == 1
    with pytest.raises(ReviewError) as failure:
        asyncio.run(decide_review(session, record.id, actor, ReviewAction.APPROVED, None))
    assert failure.value.code is ReviewErrorCode.INVALID_STATE_TRANSITION


@pytest.mark.parametrize("action", [ReviewAction.REJECTED, ReviewAction.CHANGES_REQUESTED])
def test_negative_decision_requires_a_reason(action: ReviewAction) -> None:
    with pytest.raises(ReviewError) as failure:
        asyncio.run(
            decide_review(
                AsyncMock(spec=AsyncSession),
                uuid4(),
                ReviewActor("local-reviewer", ReviewRole.REVIEWER),
                action,
                " ",
            )
        )
    assert failure.value.code is ReviewErrorCode.COMMENT_REQUIRED
