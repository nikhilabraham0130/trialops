"""The governed SQL route returns safe results and controlled failures."""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.api.dependencies import get_database_session
from trialops.api.routes.sql import _audit_sql
from trialops.core.config import RuntimeEnvironment, Settings
from trialops.main import create_app
from trialops.reviews.models import AuditEventRecord
from trialops.sql.execution import GovernedSQLResult
from trialops.sql.policy import SQLPolicyError, SQLPolicyErrorCode
from trialops.validation.alt import DatasetVersionNotFoundError


async def _post(app: FastAPI, version_id: object, sql: str) -> Response:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.post(f"/dataset-versions/{version_id}/sql", json={"candidate_sql": sql})


async def _fake_session() -> AsyncIterator[AsyncSession]:
    yield AsyncMock(spec=AsyncSession)


def test_route_returns_validated_sql_and_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    version_id = uuid4()
    app = create_app(Settings(env=RuntimeEnvironment.TEST))
    app.dependency_overrides[get_database_session] = _fake_session

    async def fake_run(_session: AsyncSession, requested_id: object, sql: str) -> GovernedSQLResult:
        assert requested_id == version_id
        assert sql == "SELECT actual_arm FROM vw_subjects"
        return GovernedSQLResult(
            dataset_version_id=version_id,
            validated_sql="SELECT actual_arm FROM vw_subjects LIMIT 100",
            row_count=1,
            row_limit=100,
            rows=({"actual_arm": "Placebo"},),
        )

    monkeypatch.setattr("trialops.api.routes.sql.run_governed_sql", fake_run)
    response = asyncio.run(_post(app, version_id, "SELECT actual_arm FROM vw_subjects"))
    assert response.status_code == 200
    assert response.json()["rows"] == [{"actual_arm": "Placebo"}]


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (
            SQLPolicyError(SQLPolicyErrorCode.POLICY_VIOLATION, "Not approved."),
            422,
            "SQL_POLICY_VIOLATION",
        ),
        (
            DatasetVersionNotFoundError("Missing version."),
            404,
            "DATASET_VERSION_NOT_FOUND",
        ),
    ],
)
def test_route_maps_safe_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception, status_code: int, code: str
) -> None:
    app = create_app(Settings(env=RuntimeEnvironment.TEST))
    app.dependency_overrides[get_database_session] = _fake_session

    async def fake_run(_session: AsyncSession, _version_id: object, _sql: str) -> GovernedSQLResult:
        raise error

    monkeypatch.setattr("trialops.api.routes.sql.run_governed_sql", fake_run)
    response = asyncio.run(_post(app, uuid4(), "SELECT * FROM vw_subjects"))
    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == code


def test_sql_audit_keeps_only_query_fingerprint() -> None:
    session = AsyncMock(spec=AsyncSession)
    candidate = "SELECT * FROM vw_subjects WHERE unique_subject_id = 'private-literal'"
    asyncio.run(_audit_sql(session, uuid4(), "SQL_REJECTED", candidate))
    record = session.add.call_args.args[0]
    assert isinstance(record, AuditEventRecord)
    assert record.details == {
        "candidate_sha256": hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    }
    assert "private-literal" not in str(record.details)
    assert session.commit.await_count == 1
