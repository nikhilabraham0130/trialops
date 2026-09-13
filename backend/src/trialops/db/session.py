"""SQLAlchemy engine and session construction."""

from dataclasses import dataclass

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from trialops.core.config import Settings


@dataclass(frozen=True, slots=True)
class DatabaseResources:
    """Long-lived engine and factory for short-lived database sessions."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    async def dispose(self) -> None:
        """Close pooled database connections during application shutdown."""
        await self.engine.dispose()


def create_database_resources(settings: Settings) -> DatabaseResources:
    """Build database resources from validated application settings."""
    database_url = make_url(settings.database_url.get_secret_value())
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return DatabaseResources(engine=engine, session_factory=session_factory)
