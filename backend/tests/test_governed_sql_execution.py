"""Execution limits role, transaction mode, version, and query runtime."""

import asyncio
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.sql.execution import (
    SQLExecutionError,
    SQLExecutionErrorCode,
    run_governed_sql,
)
from trialops.validation.alt import DatasetVersionNotFoundError


class Row:
    def __init__(self, values: dict[str, Any]) -> None:
        self._mapping = values


class Result:
    def fetchall(self) -> list[Row]:
        return [Row({"n": 306})]


class Connection:
    def __init__(self, error: SQLAlchemyError | None = None) -> None:
        self.query: str | None = None
        self.error = error

    async def exec_driver_sql(self, query: str) -> Result:
        self.query = query
        if self.error is not None:
            raise self.error
        return Result()


class Session:
    def __init__(self, version_id: UUID | None, error: SQLAlchemyError | None = None) -> None:
        self.version_id = version_id
        self.connection_value = Connection(error)
        self.statements: list[tuple[str, dict[str, str] | None]] = []
        self.rollbacks = 0

    async def scalar(self, _statement: object) -> UUID | None:
        return self.version_id

    async def execute(self, statement: object, params: dict[str, str] | None = None) -> None:
        self.statements.append((str(statement), params))

    async def connection(self) -> Connection:
        return self.connection_value

    async def rollback(self) -> None:
        self.rollbacks += 1


def test_execution_uses_restricted_read_only_transaction_and_version_setting() -> None:
    version_id = uuid4()
    session = Session(version_id)
    result = asyncio.run(
        run_governed_sql(
            cast(AsyncSession, session),
            version_id,
            "SELECT COUNT(*) AS n FROM vw_subjects",
        )
    )
    assert result.rows == ({"n": 306},)
    assert result.row_limit == 100
    assert session.connection_value.query is not None
    assert session.connection_value.query.endswith("LIMIT 100")
    assert [statement for statement, _ in session.statements] == [
        "SET TRANSACTION READ ONLY",
        "SET LOCAL ROLE trialops_reader",
        "SET LOCAL statement_timeout = '3000ms'",
        "SELECT set_config('trialops.dataset_version_id', :version_id, true)",
    ]
    assert session.statements[-1][1] == {"version_id": str(version_id)}
    assert session.rollbacks == 2


def test_execution_rejects_missing_version_before_role_change() -> None:
    session = Session(None)
    with pytest.raises(DatasetVersionNotFoundError):
        asyncio.run(
            run_governed_sql(cast(AsyncSession, session), uuid4(), "SELECT * FROM vw_subjects")
        )
    assert session.statements == []


def test_execution_hides_database_errors_and_rolls_back() -> None:
    version_id = uuid4()
    session = Session(version_id, SQLAlchemyError("secret database details"))
    with pytest.raises(SQLExecutionError) as raised:
        asyncio.run(
            run_governed_sql(cast(AsyncSession, session), version_id, "SELECT * FROM vw_subjects")
        )
    assert raised.value.code is SQLExecutionErrorCode.QUERY_FAILED
    assert "secret" not in str(raised.value)
    assert session.rollbacks == 2
