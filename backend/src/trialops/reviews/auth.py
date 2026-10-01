"""Small backend-enforced identity boundary for the local review demo."""

from dataclasses import dataclass
from enum import StrEnum
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from trialops.core.config import Settings


class ReviewRole(StrEnum):
    ANALYST = "ANALYST"
    REVIEWER = "REVIEWER"


@dataclass(frozen=True, slots=True)
class ReviewActor:
    id: str
    role: ReviewRole


def get_review_actor(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> ReviewActor:
    """Authenticate the bearer token without accepting a browser-supplied actor ID."""
    settings: Settings = request.app.state.settings
    if settings.analyst_token is None or settings.reviewer_token is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "REVIEW_NOT_CONFIGURED",
                "message": "Local review identities are not configured.",
            },
        )
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_REQUIRED", "message": "A review role token is required."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    candidate = authorization.removeprefix("Bearer ")
    analyst_match = compare_digest(candidate, settings.analyst_token.get_secret_value())
    reviewer_match = compare_digest(candidate, settings.reviewer_token.get_secret_value())
    if analyst_match:
        return ReviewActor(id="local-analyst", role=ReviewRole.ANALYST)
    if reviewer_match:
        return ReviewActor(id="local-reviewer", role=ReviewRole.REVIEWER)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "INVALID_CREDENTIALS", "message": "The review role token is invalid."},
        headers={"WWW-Authenticate": "Bearer"},
    )


ReviewIdentity = Annotated[ReviewActor, Depends(get_review_actor)]
