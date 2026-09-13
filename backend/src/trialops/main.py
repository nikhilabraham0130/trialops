"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from trialops.api.routes.health import router as health_router
from trialops.core.config import Settings, get_settings
from trialops.db.session import DatabaseResources, create_database_resources


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Release long-lived application resources during shutdown."""
    try:
        yield
    finally:
        database = application.state.database
        if isinstance(database, DatabaseResources):
            await database.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure a TrialOps API instance."""
    app_settings = settings or get_settings()
    database = create_database_resources(app_settings)
    application = FastAPI(
        title="TrialOps API",
        description="Governed clinical-trial analytics API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.database = database
    application.include_router(health_router)

    return application


app = create_app()
