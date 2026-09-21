"""Tests for the governed analysis-planning HTTP endpoint."""

import asyncio
from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.fake_model import FakePlanModel
from trialops.agent.model import PlanModelError
from trialops.agent.models import AgentPlanRecord
from trialops.api.dependencies import get_database_session
from trialops.api.routes.agent import router as agent_router
from trialops.core.config import RuntimeEnvironment, Settings
from trialops.main import create_app

VALID_RESPONSE = (
    '{"tool_name":"calculate_alt_gt_3x_uln",'
    '"purpose":"Use the approved ALT threshold calculation."}'
)


class _FakeSession:
    def __init__(
        self, version_id: UUID | None, *, commit_error: IntegrityError | None = None
    ) -> None:
        self.version_id = version_id
        self.commit_error = commit_error
        self.scalar_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0
        self.added: object | None = None

    async def scalar(self, _statement: object) -> UUID | None:
        self.scalar_calls += 1
        return self.version_id

    def add(self, instance: object) -> None:
        self.added = instance

    async def commit(self) -> None:
        self.commit_calls += 1
        if self.commit_error is not None:
            raise self.commit_error

    async def rollback(self) -> None:
        self.rollback_calls += 1


async def _post(application: FastAPI, body: dict[str, object]) -> Response:
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post("/agent/plans", json=body)


def _override_session(application: FastAPI, fake: _FakeSession) -> None:
    async def session_override() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, fake)

    application.dependency_overrides[get_database_session] = session_override


def test_plan_endpoint_returns_confirmation_required_plan() -> None:
    version_id = uuid4()
    model = FakePlanModel(VALID_RESPONSE)
    application = create_app(Settings(env=RuntimeEnvironment.TEST), plan_model=model)
    fake_session = _FakeSession(version_id)
    _override_session(application, fake_session)

    response = asyncio.run(
        _post(
            application,
            {
                "question": "Were any ALT measurements above three times the upper limit?",
                "dataset_version_id": str(version_id),
            },
        )
    )

    assert response.status_code == 201
    body = response.json()
    assert body["question"] == "Were any ALT measurements above three times the upper limit?"
    assert body["dataset_version_id"] == str(version_id)
    assert body["status"] == "AWAITING_CONFIRMATION"
    assert body["confirmation_required"] is True
    assert body["tool_call"] == {
        "name": "calculate_alt_gt_3x_uln",
        "arguments": {"dataset_version_id": str(version_id)},
    }
    assert fake_session.scalar_calls == 1
    assert fake_session.rollback_calls == 1
    assert fake_session.commit_calls == 1
    record = cast(AgentPlanRecord, fake_session.added)
    assert str(record.id) == body["id"]
    assert record.dataset_version_id == version_id
    assert len(model.requests) == 1


def test_plan_endpoint_rejects_unknown_version_before_calling_model() -> None:
    version_id = uuid4()
    model = FakePlanModel(VALID_RESPONSE)
    application = create_app(Settings(env=RuntimeEnvironment.TEST), plan_model=model)
    _override_session(application, _FakeSession(None))

    response = asyncio.run(
        _post(application, {"question": "Check ALT.", "dataset_version_id": str(version_id)})
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DATASET_VERSION_NOT_FOUND"
    assert model.requests == []


@pytest.mark.parametrize(
    ("model", "expected_status", "expected_code"),
    [
        (
            FakePlanModel("not json"),
            502,
            "INVALID_MODEL_RESPONSE",
        ),
        (
            FakePlanModel(VALID_RESPONSE, error=PlanModelError("upstream secret")),
            503,
            "MODEL_UNAVAILABLE",
        ),
    ],
)
def test_plan_endpoint_maps_model_failures_to_safe_errors(
    model: FakePlanModel, expected_status: int, expected_code: str
) -> None:
    version_id = uuid4()
    application = create_app(Settings(env=RuntimeEnvironment.TEST), plan_model=model)
    _override_session(application, _FakeSession(version_id))

    response = asyncio.run(
        _post(application, {"question": "Check ALT.", "dataset_version_id": str(version_id)})
    )

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    assert "secret" not in response.text


def test_plan_endpoint_rejects_blank_question() -> None:
    version_id = uuid4()
    model = FakePlanModel(VALID_RESPONSE)
    application = create_app(Settings(env=RuntimeEnvironment.TEST), plan_model=model)
    _override_session(application, _FakeSession(version_id))

    response = asyncio.run(
        _post(application, {"question": "   ", "dataset_version_id": str(version_id)})
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_QUESTION"


def test_plan_endpoint_returns_conflict_when_plan_cannot_be_stored() -> None:
    version_id = uuid4()
    conflict = IntegrityError("insert", {}, Exception("duplicate plan id"))
    fake_session = _FakeSession(version_id, commit_error=conflict)
    application = create_app(
        Settings(env=RuntimeEnvironment.TEST), plan_model=FakePlanModel(VALID_RESPONSE)
    )
    _override_session(application, fake_session)

    response = asyncio.run(
        _post(application, {"question": "Check ALT.", "dataset_version_id": str(version_id)})
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DATABASE_CONFLICT"
    assert fake_session.rollback_calls == 2


def test_plan_endpoint_requires_configured_model() -> None:
    version_id = uuid4()
    application = FastAPI()
    application.include_router(agent_router)
    _override_session(application, _FakeSession(version_id))

    response = asyncio.run(
        _post(application, {"question": "Check ALT.", "dataset_version_id": str(version_id)})
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Planning model is unavailable."}
