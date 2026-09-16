"""Shared FastAPI request dependencies."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

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
