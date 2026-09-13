"""FastAPI application entry point."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from trialops.core.config import Settings, get_settings


class HealthResponse(BaseModel):
    """Response returned when the API process is running."""

    status: Literal["ok"]
    service: Literal["trialops-api"]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure a TrialOps API instance."""
    app_settings = settings or get_settings()
    application = FastAPI(
        title="TrialOps API",
        description="Governed clinical-trial analytics API",
        version="0.1.0",
    )
    application.state.settings = app_settings

    @application.get(
        "/health/live",
        response_model=HealthResponse,
        summary="Check whether the API process is running",
        tags=["health"],
    )
    async def liveness() -> HealthResponse:
        """Return a successful response while the API process is alive."""
        return HealthResponse(status="ok", service="trialops-api")

    return application


app = create_app()
