"""Health-check endpoints for the TrialOps API."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    """Response returned when the API process is running."""

    status: Literal["ok"]
    service: Literal["trialops-api"]


@router.get(
    "/live",
    response_model=HealthResponse,
    summary="Check whether the API process is running",
)
async def liveness() -> HealthResponse:
    """Return a successful response while the API process is alive."""
    return HealthResponse(status="ok", service="trialops-api")
