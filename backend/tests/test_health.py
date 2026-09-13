"""Tests for API health endpoints."""

import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from trialops.api.routes.health import router as health_router
from trialops.core.config import RuntimeEnvironment, Settings
from trialops.main import create_app


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
