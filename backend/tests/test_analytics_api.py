"""Tests for deterministic analytics HTTP endpoints."""

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.analytics.lab_abnormalities import (
    METHOD_VERSION,
    AltAbnormalityResult,
    AltExceedance,
    TimingClassification,
)
from trialops.analytics.severe_adverse_events import (
    SevereAeArmResult,
    SevereAeEvidence,
    SevereAeIncidenceResult,
)
from trialops.analytics.subject_safety import (
    FlaggedLab,
    SafetyEvent,
    SubjectNotFoundError,
    SubjectSafetySummary,
)
from trialops.api.dependencies import get_database_session
from trialops.api.routes.analytics import router as analytics_router
from trialops.core.config import RuntimeEnvironment, Settings
from trialops.main import create_app
from trialops.validation.alt import DatasetVersionNotFoundError
from trialops.validation.findings import FindingSeverity, ValidationFinding


async def _request(application: FastAPI, path: str) -> Response:
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


async def _fake_session() -> AsyncIterator[AsyncSession]:
    yield AsyncSession()


def test_alt_endpoint_serializes_method_counts_evidence_and_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version_id = uuid4()
    application = create_app(Settings(env=RuntimeEnvironment.TEST))
    result = AltAbnormalityResult(
        method_version=METHOD_VERSION,
        threshold_multiplier=Decimal(3),
        alt_row_count=2,
        eligible_row_count=1,
        excluded_row_count=1,
        subjects_with_exceedance=1,
        exceedances=(
            AltExceedance(
                source_record_number=10,
                unique_subject_id="SUBJECT-001",
                standard_result=Decimal("150.5"),
                upper_reference_limit=Decimal(40),
                threshold=Decimal(120),
                timing=TimingClassification.NOT_IDENTIFIED_AS_BASELINE,
            ),
        ),
        findings=(
            ValidationFinding(
                rule_code="ALT_RESULT_MISSING_OR_INVALID",
                severity=FindingSeverity.WARNING,
                domain="LB",
                source_record_number=11,
                message="ALT result is missing or not a finite number.",
            ),
        ),
    )

    async def fake_calculation(
        _session: AsyncSession, requested_version_id: object
    ) -> AltAbnormalityResult:
        assert requested_version_id == version_id
        return result

    monkeypatch.setattr(
        "trialops.api.routes.analytics.calculate_stored_alt_gt_3x_uln",
        fake_calculation,
    )
    application.dependency_overrides[get_database_session] = _fake_session

    response = asyncio.run(
        _request(application, f"/dataset-versions/{version_id}/analytics/alt-gt-3x-uln")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dataset_version_id"] == str(version_id)
    assert body["method_version"] == "alt-gt-3x-uln/1.0"
    assert body["threshold_multiplier"] == "3"
    assert body["alt_row_count"] == 2
    assert body["eligible_row_count"] == 1
    assert body["excluded_row_count"] == 1
    assert body["qualifying_measurement_count"] == 1
    assert body["subjects_with_qualifying_measurement"] == 1
    assert body["exceedances"] == [
        {
            "source_record_number": 10,
            "unique_subject_id": "SUBJECT-001",
            "standard_result": "150.5",
            "upper_reference_limit": "40",
            "threshold": "120",
            "timing": "NOT_IDENTIFIED_AS_BASELINE",
        }
    ]
    assert body["findings"][0]["rule_code"] == "ALT_RESULT_MISSING_OR_INVALID"
    assert "does not prove" in body["timing_limitation"]


def test_alt_endpoint_returns_controlled_error_for_unknown_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version_id = uuid4()
    application = create_app(Settings(env=RuntimeEnvironment.TEST))

    async def unknown_version(_session: AsyncSession, _version_id: object) -> AltAbnormalityResult:
        raise DatasetVersionNotFoundError("The selected dataset version does not exist.")

    monkeypatch.setattr(
        "trialops.api.routes.analytics.calculate_stored_alt_gt_3x_uln",
        unknown_version,
    )
    application.dependency_overrides[get_database_session] = _fake_session

    response = asyncio.run(
        _request(application, f"/dataset-versions/{version_id}/analytics/alt-gt-3x-uln")
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "code": "DATASET_VERSION_NOT_FOUND",
            "message": "The selected dataset version does not exist.",
        }
    }


def test_alt_endpoint_requires_database_resources() -> None:
    application = FastAPI()
    application.include_router(analytics_router)

    response = asyncio.run(
        _request(application, f"/dataset-versions/{uuid4()}/analytics/alt-gt-3x-uln")
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Database resources are unavailable."}


def test_severe_ae_endpoint_serializes_population_counts_and_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version_id = uuid4()
    application = create_app(Settings(env=RuntimeEnvironment.TEST))

    async def fake_calculation(
        _session: AsyncSession, requested_version_id: object
    ) -> SevereAeIncidenceResult:
        assert requested_version_id == version_id
        return SevereAeIncidenceResult(
            method_version="severe-ae-incidence/1.0",
            excluded_screen_failure_subjects=2,
            arms=(SevereAeArmResult("Placebo", 3, 1, 2, Decimal("33.33")),),
            evidence=(SevereAeEvidence(42, "SUBJECT-001", "Placebo", "Headache"),),
        )

    monkeypatch.setattr(
        "trialops.api.routes.analytics.calculate_stored_severe_ae_incidence",
        fake_calculation,
    )
    application.dependency_overrides[get_database_session] = _fake_session

    response = asyncio.run(
        _request(application, f"/dataset-versions/{version_id}/analytics/severe-ae-incidence")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dataset_version_id"] == str(version_id)
    assert body["excluded_screen_failure_subjects"] == 2
    assert body["arms"] == [
        {
            "arm": "Placebo",
            "subjects_in_arm": 3,
            "subjects_with_severe_ae": 1,
            "severe_ae_event_count": 2,
            "incidence_percent": "33.33",
        }
    ]
    assert body["evidence"][0]["source_record_number"] == 42
    assert "not confirmed treatment-emergent" in body["timing_limitation"]
    assert "ACTARM" in body["population_definition"]


def test_severe_ae_endpoint_returns_404_for_unknown_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = create_app(Settings(env=RuntimeEnvironment.TEST))

    async def unknown_version(
        _session: AsyncSession, _version_id: object
    ) -> SevereAeIncidenceResult:
        raise DatasetVersionNotFoundError("The selected dataset version does not exist.")

    monkeypatch.setattr(
        "trialops.api.routes.analytics.calculate_stored_severe_ae_incidence",
        unknown_version,
    )
    application.dependency_overrides[get_database_session] = _fake_session

    response = asyncio.run(
        _request(application, f"/dataset-versions/{uuid4()}/analytics/severe-ae-incidence")
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DATASET_VERSION_NOT_FOUND"


def test_subject_safety_endpoint_returns_source_linked_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trialops.datasets.adverse_events import AdverseEventSeverity
    from trialops.datasets.laboratory_results import NormalRangeIndicator

    version_id = uuid4()
    application = create_app(Settings(env=RuntimeEnvironment.TEST))

    async def fake_summary(
        _session: AsyncSession, requested_version_id: object, subject_id: str
    ) -> SubjectSafetySummary:
        assert requested_version_id == version_id
        assert subject_id == "SUBJECT-001"
        return SubjectSafetySummary(
            method_version="subject-safety-summary/1.0",
            unique_subject_id=subject_id,
            actual_arm="Placebo",
            age=55,
            age_unit="YEARS",
            sex="F",
            ae_event_count=1,
            severe_ae_event_count=1,
            serious_ae_event_count=0,
            lab_result_count=2,
            flagged_lab_count=1,
            events=(SafetyEvent(10, "Headache", AdverseEventSeverity.SEVERE, "N", "2020-01-01"),),
            flagged_labs=(
                FlaggedLab(
                    20,
                    "ALT",
                    Decimal("55"),
                    "U/L",
                    Decimal("10"),
                    Decimal("40"),
                    NormalRangeIndicator.HIGH,
                    None,
                    "2020-01-02",
                ),
            ),
        )

    monkeypatch.setattr(
        "trialops.api.routes.analytics.get_stored_subject_safety_summary", fake_summary
    )
    application.dependency_overrides[get_database_session] = _fake_session
    response = asyncio.run(
        _request(
            application,
            f"/dataset-versions/{version_id}/analytics/subjects/SUBJECT-001/safety-summary",
        )
    )

    assert response.status_code == 200
    body = response.json()
    assert body["unique_subject_id"] == "SUBJECT-001"
    assert body["severe_ae_event_count"] == 1
    assert body["serious_ae_event_count"] == 0
    assert body["flagged_labs"][0]["standard_result"] == "55"
    assert "not a derived clinical diagnosis" in body["interpretation_limit"]


def test_subject_safety_endpoint_returns_controlled_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = create_app(Settings(env=RuntimeEnvironment.TEST))

    async def missing_subject(
        _session: AsyncSession, _version_id: object, _subject_id: str
    ) -> SubjectSafetySummary:
        raise SubjectNotFoundError("The subject is not in the selected dataset version.")

    monkeypatch.setattr(
        "trialops.api.routes.analytics.get_stored_subject_safety_summary", missing_subject
    )
    application.dependency_overrides[get_database_session] = _fake_session
    response = asyncio.run(
        _request(application, f"/dataset-versions/{uuid4()}/analytics/subjects/S1/safety-summary")
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SUBJECT_NOT_FOUND"


def test_subject_safety_endpoint_rejects_unknown_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = create_app(Settings(env=RuntimeEnvironment.TEST))

    async def missing_version(
        _session: AsyncSession, _version_id: object, _subject_id: str
    ) -> SubjectSafetySummary:
        raise DatasetVersionNotFoundError("The selected dataset version does not exist.")

    monkeypatch.setattr(
        "trialops.api.routes.analytics.get_stored_subject_safety_summary", missing_version
    )
    application.dependency_overrides[get_database_session] = _fake_session
    response = asyncio.run(
        _request(application, f"/dataset-versions/{uuid4()}/analytics/subjects/S1/safety-summary")
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DATASET_VERSION_NOT_FOUND"
