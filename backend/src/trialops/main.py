"""FastAPI application entry point."""

from fastapi import FastAPI

from trialops.api.routes.health import router as health_router
from trialops.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure a TrialOps API instance."""
    app_settings = settings or get_settings()
    application = FastAPI(
        title="TrialOps API",
        description="Governed clinical-trial analytics API",
        version="0.1.0",
    )
    application.state.settings = app_settings
    application.include_router(health_router)

    return application


app = create_app()
