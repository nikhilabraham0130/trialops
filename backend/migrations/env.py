"""Alembic environment for applying TrialOps database migrations."""

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import Connection, create_engine, pool

from trialops.core.config import Settings
from trialops.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def get_database_url() -> str:
    """Load the migration target without storing credentials in Alembic files."""
    # BaseSettings supports this runtime-only keyword, but its synthesized
    # constructor signature does not expose it to static type checkers.
    settings = Settings(_env_file=REPOSITORY_ROOT / ".env")  # type: ignore[call-arg]
    return settings.database_url.get_secret_value()


def run_migrations_offline() -> None:
    """Generate SQL without opening a database connection."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def apply_migrations(connection: Connection) -> None:
    """Apply pending migrations using an established connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations through one short-lived synchronous connection."""
    engine = create_engine(get_database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            apply_migrations(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
