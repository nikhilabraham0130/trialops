"""The SQL proposal route validates a selected dataset and never runs SQL."""

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.api.dependencies import get_database_session
from trialops.core.config import RuntimeEnvironment, Settings
from trialops.main import create_app
from trialops.sql.model import SQLModelRequest


class FakeSQLModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.requests: list[SQLModelRequest] = []

    async def generate_sql_json(self, request: SQLModelRequest) -> str:
        self.requests.append(request)
        return self.response


async def _post(app: FastAPI, version_id: object, question: str) -> Response:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.post(
            f"/dataset-versions/{version_id}/sql/proposals", json={"question": question}
        )


def _app_with_version(version_exists: bool, model: FakeSQLModel) -> tuple[FastAPI, AsyncMock, UUID]:
    version_id = uuid4()
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = version_id if version_exists else None

    async def fake_session() -> AsyncIterator[AsyncSession]:
        yield session

    app = create_app(Settings(env=RuntimeEnvironment.TEST), sql_model=model)
    app.dependency_overrides[get_database_session] = fake_session
    return app, session, version_id


def test_sql_proposal_route_drafts_without_executing() -> None:
    model = FakeSQLModel(
        '{"candidate_sql":"SELECT COUNT(*) AS subjects FROM vw_subjects",'
        '"purpose":"Count subjects."}'
    )
    app, session, version_id = _app_with_version(True, model)
    response = asyncio.run(_post(app, version_id, "How many subjects?"))
    assert response.status_code == 200
    assert response.json()["confirmation_required"] is True
    assert response.json()["validated_sql"].endswith("LIMIT 100")
    assert session.execute.await_count == 0
    assert len(model.requests) == 1


def test_sql_proposal_does_not_call_model_for_unknown_version() -> None:
    model = FakeSQLModel('{"candidate_sql":null,"purpose":"Unsupported."}')
    app, _session, version_id = _app_with_version(False, model)
    response = asyncio.run(_post(app, version_id, "How many subjects?"))
    assert response.status_code == 404
    assert model.requests == []


def test_sql_proposal_rejects_unsafe_model_output() -> None:
    model = FakeSQLModel('{"candidate_sql":"SELECT * FROM agent_plan","purpose":"Read plans."}')
    app, _session, version_id = _app_with_version(True, model)
    response = asyncio.run(_post(app, version_id, "Read plans"))
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "SQL_INVALID_MODEL_RESPONSE"
