"""Tests for API health endpoints."""

import asyncio

from httpx import ASGITransport, AsyncClient, Response

from trialops.core.config import RuntimeEnvironment, Settings
from trialops.main import create_app


async def _request_liveness() -> Response:
    """Send a request directly to the ASGI application."""
    settings = Settings(env=RuntimeEnvironment.TEST)
    transport = ASGITransport(app=create_app(settings))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get("/health/live")


def test_liveness_returns_service_status() -> None:
    """The liveness endpoint identifies a running TrialOps API process."""
    response = asyncio.run(_request_liveness())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "trialops-api"}
