"""Tests for the governed analysis-planning HTTP endpoint."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.contracts import (
    AltThresholdToolInput,
    AnalysisExecution,
    AnalysisPlanDetails,
    ApprovedToolCall,
    ApprovedToolName,
    PlanStatus,
)
from trialops.agent.execution import AgentExecutionError, AgentExecutionErrorCode
from trialops.agent.fake_interpretation_model import FakeInterpretationModel
from trialops.agent.fake_model import FakePlanModel
from trialops.agent.interpretation_contracts import GroundingStatus, StoredInterpretation
from trialops.agent.interpretation_model import InterpretationModel
from trialops.agent.interpretation_workflow import (
    InterpretationWorkflowError,
    InterpretationWorkflowErrorCode,
)
from trialops.agent.model import PlanModelError
from trialops.agent.models import AgentPlanRecord
from trialops.agent.queries import AgentPlanQueryError, AgentPlanQueryErrorCode
from trialops.analytics.contracts import AltAbnormalityResponse
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


async def _confirm(application: FastAPI, plan_id: UUID, confirmed: bool = True) -> Response:
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(
            f"/agent/plans/{plan_id}/confirm",
            json={"confirmed": confirmed},
        )


async def _get_plan(application: FastAPI, plan_id: UUID) -> Response:
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(f"/agent/plans/{plan_id}")


async def _interpret(application: FastAPI, plan_id: UUID) -> Response:
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(f"/agent/plans/{plan_id}/interpretation")


def _override_session(application: FastAPI, fake: _FakeSession) -> None:
    async def session_override() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, fake)

    application.dependency_overrides[get_database_session] = session_override


def _execution(plan_id: UUID, dataset_version_id: UUID) -> AnalysisExecution:
    return AnalysisExecution(
        plan_id=plan_id,
        status=PlanStatus.EXECUTED,
        tool_name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
        result=AltAbnormalityResponse(
            dataset_version_id=dataset_version_id,
            method_version="alt-gt-3x-uln/1.0",
            threshold_multiplier=Decimal(3),
            alt_row_count=1,
            eligible_row_count=1,
            excluded_row_count=0,
            qualifying_measurement_count=0,
            subjects_with_qualifying_measurement=0,
            exceedances=(),
            findings=(),
            timing_limitation="A blank baseline flag does not prove post-treatment timing.",
        ),
    )


def _details(plan_id: UUID, dataset_version_id: UUID) -> AnalysisPlanDetails:
    return AnalysisPlanDetails(
        id=plan_id,
        question="Check ALT.",
        dataset_version_id=dataset_version_id,
        purpose="Use the approved deterministic ALT calculation.",
        status=PlanStatus.AWAITING_CONFIRMATION,
        confirmation_required=True,
        tool_call=ApprovedToolCall(
            name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
            arguments=AltThresholdToolInput(dataset_version_id=dataset_version_id),
        ),
        result=None,
        interpretation=None,
        created_at=datetime(2026, 9, 22, 12, tzinfo=UTC),
        executed_at=None,
    )


def _stored_interpretation() -> StoredInterpretation:
    return StoredInterpretation(
        summary="The deterministic calculation completed.",
        numeric_claims=(),
        grounding_status=GroundingStatus.NUMERICALLY_VERIFIED,
        prompt_version="alt-result-interpretation/1.0",
        model_id="fake-model-v1",
        generated_at=datetime(2026, 9, 23, 12, tzinfo=UTC),
    )


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


def test_confirmation_endpoint_executes_stored_plan_without_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_id = uuid4()
    version_id = uuid4()
    fake_session = _FakeSession(None)
    application = create_app(Settings(env=RuntimeEnvironment.TEST))
    _override_session(application, fake_session)

    async def execute(session: AsyncSession, requested_plan_id: UUID) -> AnalysisExecution:
        assert session is cast(AsyncSession, fake_session)
        assert requested_plan_id == plan_id
        return _execution(plan_id, version_id)

    monkeypatch.setattr("trialops.api.routes.agent.execute_confirmed_plan", execute)

    response = asyncio.run(_confirm(application, plan_id))

    assert response.status_code == 200
    assert response.json()["plan_id"] == str(plan_id)
    assert response.json()["status"] == "EXECUTED"
    assert response.json()["result"]["dataset_version_id"] == str(version_id)


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        (AgentExecutionErrorCode.PLAN_NOT_FOUND, 404),
        (AgentExecutionErrorCode.PLAN_NOT_CONFIRMABLE, 409),
    ],
)
def test_confirmation_endpoint_maps_safe_execution_errors(
    monkeypatch: pytest.MonkeyPatch,
    code: AgentExecutionErrorCode,
    expected_status: int,
) -> None:
    plan_id = uuid4()
    application = create_app(Settings(env=RuntimeEnvironment.TEST))
    _override_session(application, _FakeSession(None))

    async def reject(_session: AsyncSession, _plan_id: UUID) -> AnalysisExecution:
        raise AgentExecutionError(code, "Safe explanation.")

    monkeypatch.setattr("trialops.api.routes.agent.execute_confirmed_plan", reject)

    response = asyncio.run(_confirm(application, plan_id))

    assert response.status_code == expected_status
    assert response.json()["detail"] == {
        "code": code.value,
        "message": "Safe explanation.",
    }


def test_confirmation_endpoint_requires_explicit_true_decision() -> None:
    application = create_app(Settings(env=RuntimeEnvironment.TEST))
    _override_session(application, _FakeSession(None))

    response = asyncio.run(_confirm(application, uuid4(), confirmed=False))

    assert response.status_code == 422


def test_retrieval_endpoint_returns_stored_plan_without_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_id = uuid4()
    version_id = uuid4()
    fake_session = _FakeSession(None)
    application = create_app(Settings(env=RuntimeEnvironment.TEST))
    _override_session(application, fake_session)

    async def retrieve(session: AsyncSession, requested_plan_id: UUID) -> AnalysisPlanDetails:
        assert session is cast(AsyncSession, fake_session)
        assert requested_plan_id == plan_id
        return _details(plan_id, version_id)

    monkeypatch.setattr("trialops.api.routes.agent.get_analysis_plan", retrieve)

    response = asyncio.run(_get_plan(application, plan_id))

    assert response.status_code == 200
    assert response.json()["id"] == str(plan_id)
    assert response.json()["status"] == "AWAITING_CONFIRMATION"
    assert response.json()["confirmation_required"] is True
    assert response.json()["result"] is None


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        (AgentPlanQueryErrorCode.PLAN_NOT_FOUND, 404),
        (AgentPlanQueryErrorCode.INVALID_STORED_PLAN, 409),
    ],
)
def test_retrieval_endpoint_maps_safe_query_errors(
    monkeypatch: pytest.MonkeyPatch,
    code: AgentPlanQueryErrorCode,
    expected_status: int,
) -> None:
    plan_id = uuid4()
    application = create_app(Settings(env=RuntimeEnvironment.TEST))
    _override_session(application, _FakeSession(None))

    async def reject(_session: AsyncSession, _plan_id: UUID) -> AnalysisPlanDetails:
        raise AgentPlanQueryError(code, "Safe explanation.")

    monkeypatch.setattr("trialops.api.routes.agent.get_analysis_plan", reject)

    response = asyncio.run(_get_plan(application, plan_id))

    assert response.status_code == expected_status
    assert response.json()["detail"] == {
        "code": code.value,
        "message": "Safe explanation.",
    }


def test_interpretation_endpoint_stores_verified_explanation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_id = uuid4()
    fake_session = _FakeSession(None)
    model = FakeInterpretationModel('{"summary":"The calculation completed.","numeric_claims":[]}')
    application = create_app(
        Settings(env=RuntimeEnvironment.TEST),
        interpretation_model=model,
    )
    _override_session(application, fake_session)

    async def create(
        session: AsyncSession,
        provider: InterpretationModel,
        requested_plan_id: UUID,
    ) -> StoredInterpretation:
        assert session is cast(AsyncSession, fake_session)
        assert provider is cast(InterpretationModel, model)
        assert requested_plan_id == plan_id
        return _stored_interpretation()

    monkeypatch.setattr(
        "trialops.api.routes.agent.create_verified_plan_interpretation",
        create,
    )

    response = asyncio.run(_interpret(application, plan_id))

    assert response.status_code == 201
    assert response.json()["grounding_status"] == "NUMERICALLY_VERIFIED"
    assert response.json()["model_id"] == "fake-model-v1"


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        (InterpretationWorkflowErrorCode.PLAN_NOT_FOUND, 404),
        (InterpretationWorkflowErrorCode.MODEL_UNAVAILABLE, 503),
        (InterpretationWorkflowErrorCode.INVALID_MODEL_RESPONSE, 502),
        (InterpretationWorkflowErrorCode.PLAN_NOT_EXECUTED, 409),
    ],
)
def test_interpretation_endpoint_maps_safe_workflow_errors(
    monkeypatch: pytest.MonkeyPatch,
    code: InterpretationWorkflowErrorCode,
    expected_status: int,
) -> None:
    plan_id = uuid4()
    model = FakeInterpretationModel('{"summary":"The calculation completed.","numeric_claims":[]}')
    application = create_app(
        Settings(env=RuntimeEnvironment.TEST),
        interpretation_model=model,
    )
    _override_session(application, _FakeSession(None))

    async def reject(
        _session: AsyncSession,
        _provider: InterpretationModel,
        _plan_id: UUID,
    ) -> StoredInterpretation:
        raise InterpretationWorkflowError(code, "Safe explanation.")

    monkeypatch.setattr(
        "trialops.api.routes.agent.create_verified_plan_interpretation",
        reject,
    )

    response = asyncio.run(_interpret(application, plan_id))

    assert response.status_code == expected_status
    assert response.json()["detail"] == {
        "code": code.value,
        "message": "Safe explanation.",
    }


def test_interpretation_endpoint_requires_configured_model() -> None:
    application = create_app(Settings(env=RuntimeEnvironment.TEST))
    _override_session(application, _FakeSession(None))

    response = asyncio.run(_interpret(application, uuid4()))

    assert response.status_code == 503
    assert response.json() == {"detail": "Interpretation model is unavailable."}
