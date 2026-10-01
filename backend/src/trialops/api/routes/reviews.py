"""Authenticated submission and independent review endpoints."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from trialops.api.dependencies import DatabaseSession
from trialops.reviews.auth import ReviewIdentity
from trialops.reviews.contracts import ReviewAction, ReviewStatus
from trialops.reviews.service import (
    ReviewError,
    ReviewErrorCode,
    decide_review,
    get_review_status,
    submit_analysis,
)

router = APIRouter(prefix="/agent/plans", tags=["reviews"])


class ReviewDecisionRequest(BaseModel):
    action: Literal[ReviewAction.APPROVED, ReviewAction.CHANGES_REQUESTED, ReviewAction.REJECTED]
    comment: str | None = Field(default=None, max_length=2000)


def _http_error(error: ReviewError) -> HTTPException:
    status_code = {
        ReviewErrorCode.PLAN_NOT_FOUND: status.HTTP_404_NOT_FOUND,
        ReviewErrorCode.ROLE_NOT_PERMITTED: status.HTTP_403_FORBIDDEN,
        ReviewErrorCode.COMMENT_REQUIRED: status.HTTP_422_UNPROCESSABLE_CONTENT,
    }.get(error.code, status.HTTP_409_CONFLICT)
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code.value, "message": str(error)},
    )


@router.get("/{plan_id}/review", response_model=ReviewStatus)
async def read_review(plan_id: UUID, session: DatabaseSession) -> ReviewStatus:
    """Show current review state and the full decision history."""
    try:
        return await get_review_status(session, plan_id)
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.post("/{plan_id}/submit", response_model=ReviewStatus)
async def submit_plan(
    plan_id: UUID, session: DatabaseSession, actor: ReviewIdentity
) -> ReviewStatus:
    """Require an analyst token and passing prerequisites before submission."""
    try:
        return await submit_analysis(session, plan_id, actor)
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.post("/{plan_id}/review", response_model=ReviewStatus)
async def review_plan(
    plan_id: UUID, request: ReviewDecisionRequest, session: DatabaseSession, actor: ReviewIdentity
) -> ReviewStatus:
    """Require a reviewer token and a different submitting identity."""
    try:
        return await decide_review(
            session, plan_id, actor, ReviewAction(request.action), request.comment
        )
    except ReviewError as exc:
        raise _http_error(exc) from exc
