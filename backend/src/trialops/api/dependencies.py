"""Shared FastAPI request dependencies."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.interpretation_model import InterpretationModel
from trialops.agent.model import PlanModel
from trialops.db.session import DatabaseResources


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one short-lived database session for an HTTP request."""
    database = getattr(request.app.state, "database", None)
    if not isinstance(database, DatabaseResources):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database resources are unavailable.",
        )

    async with database.session_factory() as session:
        yield session


DatabaseSession = Annotated[AsyncSession, Depends(get_database_session)]


def get_plan_model(request: Request) -> PlanModel:
    """Return the configured model adapter without exposing provider details."""
    model = getattr(request.app.state, "plan_model", None)
    if not isinstance(model, PlanModel):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Planning model is unavailable.",
        )
    return model


PlanningModel = Annotated[PlanModel, Depends(get_plan_model)]


def get_interpretation_model(request: Request) -> InterpretationModel:
    """Return the configured explanation model without exposing provider details."""
    model = getattr(request.app.state, "interpretation_model", None)
    if not isinstance(model, InterpretationModel):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Interpretation model is unavailable.",
        )
    return model


InterpretationProvider = Annotated[InterpretationModel, Depends(get_interpretation_model)]
