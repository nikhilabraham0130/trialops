"""Tests for study catalog HTTP endpoints and database dependency handling."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.api.dependencies import get_database_session
from trialops.api.routes.studies import router as studies_router
from trialops.core.config import RuntimeEnvironment, Settings
from trialops.datasets.models import DatasetVersionStatus
from trialops.main import create_app
from trialops.studies.queries import DatasetVersionSubjectCount, StudySummary


async def _request(application: FastAPI, path: str) -> Response:
    """Send a request directly to the ASGI application."""
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


def test_database_dependency_opens_and_closes_request_session() -> None:
    """Each request receives a usable session that is closed afterward."""
    application = create_app(Settings(env=RuntimeEnvironment.TEST))
    request = Request({"type": "http", "app": application})

    async def use_dependency() -> None:
        dependency = cast(
            AsyncGenerator[AsyncSession, None],
            get_database_session(request),
        )
        session = await anext(dependency)
        assert isinstance(session, AsyncSession)
        assert session.is_active
        await dependency.aclose()
        await application.state.database.dispose()

    asyncio.run(use_dependency())


def test_studies_endpoint_serializes_query_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The frontend receives study, version, status, and subject-count fields."""
    study_id = uuid4()
    dataset_version_id = uuid4()
    application = create_app(Settings(env=RuntimeEnvironment.TEST))

    async def fake_session() -> AsyncIterator[AsyncSession]:
        yield AsyncSession()

    async def fake_summaries(_session: AsyncSession) -> tuple[StudySummary, ...]:
        return (
            StudySummary(
                id=study_id,
                study_oid="CDISCPILOT01",
                title=None,
                dataset_versions=(
                    DatasetVersionSubjectCount(
                        id=dataset_version_id,
                        version_label="pilot-v1",
                        status=DatasetVersionStatus.RECEIVED,
                        subject_count=306,
                    ),
                ),
            ),
        )

    monkeypatch.setattr("trialops.api.routes.studies.list_study_summaries", fake_summaries)
    application.dependency_overrides[get_database_session] = fake_session

    response = asyncio.run(_request(application, "/studies"))

    assert response.status_code == 200
    assert response.json() == {
        "studies": [
            {
                "id": str(study_id),
                "study_oid": "CDISCPILOT01",
                "title": None,
                "dataset_versions": [
                    {
                        "id": str(dataset_version_id),
                        "version_label": "pilot-v1",
                        "status": "RECEIVED",
                        "subject_count": 306,
                    }
                ],
            }
        ]
    }


def test_studies_endpoint_requires_database_resources() -> None:
    """An incompletely initialized app returns a controlled availability error."""
    application = FastAPI()
    application.include_router(studies_router)

    response = asyncio.run(_request(application, "/studies"))

    assert response.status_code == 503
    assert response.json() == {"detail": "Database resources are unavailable."}
