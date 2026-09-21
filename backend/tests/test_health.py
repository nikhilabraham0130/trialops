"""Tests for API health endpoints."""

import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from trialops.api.routes.health import router as health_router
from trialops.core.config import RuntimeEnvironment, Settings
from trialops.db.session import DatabaseResources
from trialops.main import create_app, lifespan


async def _request(application: FastAPI, path: str) -> Response:
    """Send a request directly to the ASGI application."""
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


def test_liveness_returns_service_status() -> None:
    """The liveness endpoint identifies a running TrialOps API process."""
    application = create_app(Settings(env=RuntimeEnvironment.TEST))
    response = asyncio.run(_request(application, "/health/live"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "trialops-api"}


def test_application_allows_configured_frontend_origin() -> None:
    """The local React application can read API responses in a browser."""
    application = create_app(Settings(env=RuntimeEnvironment.TEST))

    async def request_with_origin() -> Response:
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(
                "/health/live",
                headers={"Origin": "http://localhost:5173"},
            )

    response = asyncio.run(request_with_origin())

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_application_allows_frontend_to_post_plan_requests() -> None:
    """CORS permits the browser's preflight for controlled plan creation."""
    application = create_app(Settings(env=RuntimeEnvironment.TEST))

    async def request_preflight() -> Response:
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.options(
                "/agent/plans",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "POST",
                },
            )

    response = asyncio.run(request_preflight())

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_readiness_confirms_application_configuration() -> None:
    """The readiness endpoint confirms validated settings are available."""
    application = create_app(Settings(env=RuntimeEnvironment.TEST))
    response = asyncio.run(_request(application, "/health/ready"))

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "trialops-api",
        "checks": {"configuration": "ok"},
    }


def test_readiness_fails_without_application_configuration() -> None:
    """The readiness endpoint rejects an incompletely initialized application."""
    application = FastAPI()
    application.include_router(health_router)

    response = asyncio.run(_request(application, "/health/ready"))

    assert response.status_code == 503
    assert response.json() == {"detail": "Application configuration is unavailable."}


def test_application_lifespan_disposes_database_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Application shutdown releases the database connection pool."""
    application = create_app(Settings(env=RuntimeEnvironment.TEST))
    disposed = False

    async def record_disposal(database: DatabaseResources) -> None:
        nonlocal disposed
        disposed = True

    monkeypatch.setattr(DatabaseResources, "dispose", record_disposal)

    async def run_lifespan() -> None:
        async with application.router.lifespan_context(application):
            assert not disposed
        assert disposed

    asyncio.run(run_lifespan())


def test_application_lifespan_ignores_non_database_state() -> None:
    """Shutdown remains safe if initialization did not create database resources."""
    application = FastAPI(lifespan=lifespan)
    application.state.database = None

    async def run_lifespan() -> None:
        async with application.router.lifespan_context(application):
            pass

    asyncio.run(run_lifespan())
