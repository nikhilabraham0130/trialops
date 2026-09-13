"""Health-check endpoints for the TrialOps API."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from trialops.core.config import Settings

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    """Response returned when the API process is running."""

    status: Literal["ok"]
    service: Literal["trialops-api"]


class ReadinessChecks(BaseModel):
    """Individual setup checks required before the API receives traffic."""

    configuration: Literal["ok"]


class ReadinessResponse(BaseModel):
    """Response returned when the API is ready to serve requests."""

    status: Literal["ready"]
    service: Literal["trialops-api"]
    checks: ReadinessChecks


@router.get(
    "/live",
    response_model=HealthResponse,
    summary="Check whether the API process is running",
)
async def liveness() -> HealthResponse:
    """Return a successful response while the API process is alive."""
    return HealthResponse(status="ok", service="trialops-api")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Check whether the API is ready to receive traffic",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Application initialization is incomplete",
        }
    },
)
async def readiness(request: Request) -> ReadinessResponse:
    """Confirm that validated application configuration is available."""
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application configuration is unavailable.",
        )

    return ReadinessResponse(
        status="ready",
        service="trialops-api",
        checks=ReadinessChecks(configuration="ok"),
    )
