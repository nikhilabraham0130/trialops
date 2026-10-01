"""Execute approved SQL inside a version-scoped, restricted read-only transaction."""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.datasets.models import DatasetVersion
from trialops.sql.policy import MAX_ROWS, validate_clinical_sql
from trialops.validation.alt import DatasetVersionNotFoundError


class SQLExecutionErrorCode(StrEnum):
    QUERY_FAILED = "SQL_QUERY_FAILED"


class SQLExecutionError(RuntimeError):
    def __init__(self, code: SQLExecutionErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class GovernedSQLResult(BaseModel):
    """Rows returned by one approved query, with its enforced limits."""

    dataset_version_id: UUID
    validated_sql: str
    row_count: int
    row_limit: int
    rows: tuple[dict[str, Any], ...]


async def run_governed_sql(
    session: AsyncSession, dataset_version_id: UUID, candidate_sql: str
) -> GovernedSQLResult:
    """Validate before DB access, then restrict role, version, time, and writes."""
    validated_sql = validate_clinical_sql(candidate_sql)
    version_exists = await session.scalar(
        select(DatasetVersion.id).where(DatasetVersion.id == dataset_version_id)
    )
    await session.rollback()
    if version_exists is None:
        raise DatasetVersionNotFoundError("The selected dataset version does not exist.")

    try:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text("SET LOCAL ROLE trialops_reader"))
        await session.execute(text("SET LOCAL statement_timeout = '3000ms'"))
        await session.execute(
            text("SELECT set_config('trialops.dataset_version_id', :version_id, true)"),
            {"version_id": str(dataset_version_id)},
        )
        connection = await session.connection()
        result = await connection.exec_driver_sql(validated_sql)
        rows = tuple(dict(row._mapping) for row in result.fetchall())
    except SQLAlchemyError as exc:
        raise SQLExecutionError(
            SQLExecutionErrorCode.QUERY_FAILED,
            "The approved SQL query could not be completed.",
        ) from exc
    finally:
        await session.rollback()

    return GovernedSQLResult(
        dataset_version_id=dataset_version_id,
        validated_sql=validated_sql,
        row_count=len(rows),
        row_limit=MAX_ROWS,
        rows=rows,
    )
