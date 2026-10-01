"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from trialops.agent.deepseek import DeepSeekModelAdapter
from trialops.agent.interpretation_model import InterpretationModel
from trialops.agent.model import PlanModel
from trialops.api.routes.agent import router as agent_router
from trialops.api.routes.analytics import router as analytics_router
from trialops.api.routes.audit import router as audit_router
from trialops.api.routes.health import router as health_router
from trialops.api.routes.reviews import router as reviews_router
from trialops.api.routes.sql import router as sql_router
from trialops.api.routes.studies import router as studies_router
from trialops.core.config import Settings, get_settings
from trialops.db.session import DatabaseResources, create_database_resources
from trialops.sql.model import SQLModel


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Release long-lived application resources during shutdown."""
    try:
        yield
    finally:
        database = application.state.database
        if isinstance(database, DatabaseResources):
            await database.dispose()


def create_app(
    settings: Settings | None = None,
    *,
    plan_model: PlanModel | None = None,
    interpretation_model: InterpretationModel | None = None,
    sql_model: SQLModel | None = None,
) -> FastAPI:
    """Create and configure a TrialOps API instance."""
    app_settings = settings or get_settings()
    configured_model: DeepSeekModelAdapter | None = None
    if app_settings.llm_api_key is not None:
        configured_model = DeepSeekModelAdapter(
            api_key=app_settings.llm_api_key,
            base_url=str(app_settings.llm_base_url),
            model=app_settings.llm_model,
        )
    database = create_database_resources(app_settings)
    application = FastAPI(
        title="TrialOps API",
        description="Governed clinical-trial analytics API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.database = database
    application.state.plan_model = plan_model if plan_model is not None else configured_model
    application.state.interpretation_model = (
        interpretation_model if interpretation_model is not None else configured_model
    )
    application.state.sql_model = sql_model if sql_model is not None else configured_model
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    application.include_router(agent_router)
    application.include_router(audit_router)
    application.include_router(analytics_router)
    application.include_router(health_router)
    application.include_router(reviews_router)
    application.include_router(studies_router)
    application.include_router(sql_router)

    return application


app = create_app()
