"""HTTP review actions preserve the authenticated actor and safe error codes."""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.api.dependencies import get_database_session
from trialops.core.config import RuntimeEnvironment, Settings
from trialops.main import create_app
from trialops.reviews.auth import ReviewActor, ReviewRole
from trialops.reviews.contracts import ReviewAction, ReviewState, ReviewStatus
from trialops.reviews.service import ReviewError, ReviewErrorCode


async def _session() -> AsyncIterator[AsyncSession]:
    yield AsyncSession()


def _app() -> FastAPI:
    app = create_app(
        Settings(
            env=RuntimeEnvironment.TEST,
            analyst_token=SecretStr("a" * 32),
            reviewer_token=SecretStr("r" * 32),
        )
    )
    app.dependency_overrides[get_database_session] = _session
    return app


async def _post(
    app: FastAPI, path: str, token: str | None, body: dict[str, object] | None = None
) -> Response:
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.post(path, headers=headers, json=body)


def test_submit_route_uses_server_derived_analyst_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()
    plan_id = uuid4()

    async def submit(
        _session: AsyncSession, requested_id: UUID, actor: ReviewActor
    ) -> ReviewStatus:
        assert requested_id == plan_id
        assert actor == ReviewActor("local-analyst", ReviewRole.ANALYST)
        return ReviewStatus(
            plan_id=plan_id,
            state=ReviewState.PENDING_REVIEW,
            submitted_by=actor.id,
            submitted_at=None,
            history=(),
        )

    monkeypatch.setattr("trialops.api.routes.reviews.submit_analysis", submit)
    response = asyncio.run(_post(app, f"/agent/plans/{plan_id}/submit", "a" * 32))
    assert response.status_code == 200
    assert response.json()["submitted_by"] == "local-analyst"


def test_review_route_uses_server_derived_reviewer_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    plan_id = uuid4()

    async def decide(
        _session: AsyncSession,
        requested_id: UUID,
        actor: ReviewActor,
        action: ReviewAction,
        comment: str | None,
    ) -> ReviewStatus:
        assert requested_id == plan_id
        assert actor == ReviewActor("local-reviewer", ReviewRole.REVIEWER)
        assert action is ReviewAction.APPROVED
        assert comment == "Verified."
        return ReviewStatus(
            plan_id=plan_id,
            state=ReviewState.APPROVED,
            submitted_by="local-analyst",
            submitted_at=None,
            history=(),
        )

    monkeypatch.setattr("trialops.api.routes.reviews.decide_review", decide)
    response = asyncio.run(
        _post(
            app,
            f"/agent/plans/{plan_id}/review",
            "r" * 32,
            {"action": "APPROVED", "comment": "Verified."},
        )
    )
    assert response.status_code == 200
    assert response.json()["state"] == "APPROVED"


def test_review_endpoint_rejects_missing_token() -> None:
    response = asyncio.run(_post(_app(), f"/agent/plans/{uuid4()}/submit", None))
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_review_endpoint_maps_independent_reviewer_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()

    async def conflict(
        _session: AsyncSession,
        _plan_id: UUID,
        _actor: ReviewActor,
        _action: ReviewAction,
        _comment: str | None,
    ) -> ReviewStatus:
        raise ReviewError(ReviewErrorCode.REVIEWER_CONFLICT, "Cannot self-review.")

    monkeypatch.setattr("trialops.api.routes.reviews.decide_review", conflict)
    response = asyncio.run(
        _post(app, f"/agent/plans/{uuid4()}/review", "r" * 32, {"action": "APPROVED"})
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "REVIEWER_CONFLICT"
