"""Audit route exposes only one entity's bounded business history."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.api.dependencies import get_database_session
from trialops.audit.service import AuditEvent
from trialops.core.config import RuntimeEnvironment, Settings
from trialops.main import create_app


async def _session() -> AsyncIterator[AsyncSession]:
    yield AsyncSession()


async def _get(app: FastAPI, entity_id: UUID, limit: int = 100) -> tuple[int, object]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"/audit/events?entity_id={entity_id}&limit={limit}")
        return response.status_code, response.json()


def test_audit_endpoint_passes_entity_scope_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    entity_id = uuid4()
    app = create_app(Settings(env=RuntimeEnvironment.TEST))
    app.dependency_overrides[get_database_session] = _session

    async def fake_list(
        _session: AsyncSession, selected_id: UUID, *, limit: int
    ) -> tuple[AuditEvent, ...]:
        assert selected_id == entity_id
        assert limit == 5
        return (
            AuditEvent(
                id=uuid4(),
                created_at=datetime.now(UTC),
                actor_id="local-operator",
                action="ANALYSIS_CREATED",
                entity_type="agent_plan",
                entity_id=entity_id,
                details={},
            ),
        )

    monkeypatch.setattr("trialops.api.routes.audit.list_audit_events", fake_list)
    status_code, body = asyncio.run(_get(app, entity_id, 5))
    assert status_code == 200
    assert isinstance(body, list)
    assert body[0]["action"] == "ANALYSIS_CREATED"


def test_audit_endpoint_rejects_unbounded_limit() -> None:
    app = create_app(Settings(env=RuntimeEnvironment.TEST))
    status_code, _body = asyncio.run(_get(app, uuid4(), 1000))
    assert status_code == 422
