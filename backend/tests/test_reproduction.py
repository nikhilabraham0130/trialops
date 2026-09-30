"""A fresh deterministic calculation must match the saved structured result."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.contracts import (
    AltThresholdToolInput,
    AnalysisPlanDetails,
    ApprovedToolCall,
    ApprovedToolName,
    PlanStatus,
    SubjectSafetyToolInput,
)
from trialops.analytics.contracts import AltAbnormalityResponse, SubjectSafetySummaryResponse
from trialops.analytics.lab_abnormalities import AltAbnormalityResult
from trialops.analytics.subject_safety import SubjectSafetySummary
from trialops.lineage.reproduction import (
    ReproductionError,
    ReproductionErrorCode,
    compare_structured_results,
    reproduce_analysis_plan,
)


class ExampleResult(BaseModel):
    count: int
    evidence: list[dict[str, int]]


def test_field_comparison_hashes_exact_match_and_reports_nested_mismatch() -> None:
    plan_id, version_id = uuid4(), uuid4()
    stored = ExampleResult(count=1, evidence=[{"row": 3}])
    matching = compare_structured_results(
        plan_id=plan_id,
        dataset_version_id=version_id,
        tool_name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
        stored=stored,
        reproduced=ExampleResult(count=1, evidence=[{"row": 3}]),
    )
    assert matching.status == "EXACT_MATCH"
    assert matching.stored_result_sha256 == matching.reproduced_result_sha256
    assert matching.difference_count == 0

    changed = compare_structured_results(
        plan_id=plan_id,
        dataset_version_id=version_id,
        tool_name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
        stored=stored,
        reproduced=ExampleResult(count=2, evidence=[{"row": 4}]),
    )
    assert changed.status == "MISMATCH"
    assert changed.stored_result_sha256 != changed.reproduced_result_sha256
    assert [(item.path, item.stored, item.reproduced) for item in changed.differences] == [
        ("count", 1, 2),
        ("evidence[0].row", 3, 4),
    ]


def test_difference_list_is_bounded_but_total_count_is_retained() -> None:
    class Many(BaseModel):
        values: list[int]

    comparison = compare_structured_results(
        plan_id=uuid4(),
        dataset_version_id=uuid4(),
        tool_name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
        stored=Many(values=[0] * 60),
        reproduced=Many(values=[1] * 60),
    )
    assert comparison.difference_count == 60
    assert len(comparison.differences) == 50
    assert comparison.differences_truncated


def _plan(*, executed: bool = True) -> AnalysisPlanDetails:
    version_id = uuid4()
    return AnalysisPlanDetails(
        id=uuid4(),
        question="Check ALT.",
        dataset_version_id=version_id,
        purpose="Run the ALT tool.",
        status=PlanStatus.EXECUTED if executed else PlanStatus.AWAITING_CONFIRMATION,
        confirmation_required=not executed,
        tool_call=ApprovedToolCall(
            name=ApprovedToolName.CALCULATE_ALT_GT_3X_ULN,
            arguments=AltThresholdToolInput(dataset_version_id=version_id),
        ),
        result=AltAbnormalityResponse(
            dataset_version_id=version_id,
            method_version="alt-gt-3x-uln/1.0",
            threshold_multiplier=Decimal(3),
            alt_row_count=1,
            eligible_row_count=1,
            excluded_row_count=0,
            qualifying_measurement_count=0,
            subjects_with_qualifying_measurement=0,
            exceedances=(),
            findings=(),
            timing_limitation=(
                "A blank baseline flag means not identified as baseline; it does not prove "
                "collection occurred after treatment began."
            ),
        )
        if executed
        else None,
        interpretation=None,
        created_at=datetime.now(UTC),
        executed_at=datetime.now(UTC) if executed else None,
    )


def test_reproduction_rejects_unexecuted_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(executed=False)

    async def fake_plan(_session: AsyncSession, _plan_id: object) -> AnalysisPlanDetails:
        return plan

    monkeypatch.setattr("trialops.lineage.reproduction.get_analysis_plan", fake_plan)
    with pytest.raises(ReproductionError) as raised:
        asyncio.run(reproduce_analysis_plan(cast(AsyncSession, object()), plan.id))
    assert raised.value.code is ReproductionErrorCode.PLAN_NOT_EXECUTED


def test_reproduction_reruns_alt_with_saved_version(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan()

    async def fake_plan(_session: AsyncSession, _plan_id: object) -> AnalysisPlanDetails:
        return plan

    async def fake_calculation(_session: AsyncSession, version_id: object) -> AltAbnormalityResult:
        assert version_id == plan.dataset_version_id
        return AltAbnormalityResult(
            method_version="alt-gt-3x-uln/1.0",
            threshold_multiplier=Decimal(3),
            alt_row_count=1,
            eligible_row_count=1,
            excluded_row_count=0,
            subjects_with_exceedance=0,
            exceedances=(),
            findings=(),
        )

    monkeypatch.setattr("trialops.lineage.reproduction.get_analysis_plan", fake_plan)
    monkeypatch.setattr(
        "trialops.lineage.reproduction.calculate_stored_alt_gt_3x_uln", fake_calculation
    )
    comparison = asyncio.run(reproduce_analysis_plan(cast(AsyncSession, object()), plan.id))
    assert comparison.status == "EXACT_MATCH"


def test_reproduction_uses_saved_subject_id(monkeypatch: pytest.MonkeyPatch) -> None:
    original = _plan()
    result = SubjectSafetySummaryResponse(
        dataset_version_id=original.dataset_version_id,
        method_version="subject-safety-summary/1.0",
        unique_subject_id="S1",
        actual_arm="Placebo",
        age=55,
        age_unit="YEARS",
        sex="F",
        ae_event_count=0,
        severe_ae_event_count=0,
        serious_ae_event_count=0,
        lab_result_count=0,
        flagged_lab_count=0,
        events=(),
        flagged_labs=(),
        interpretation_limit=(
            "AE severity (AESEV) and seriousness (AESER) are distinct. Flagged labs use the "
            "source LBNRIND classification, not a derived clinical diagnosis. Event timing "
            "and treatment emergence have not been assessed."
        ),
    )
    plan = original.model_copy(
        update={
            "tool_call": ApprovedToolCall(
                name=ApprovedToolName.GET_SUBJECT_SAFETY_SUMMARY,
                arguments=SubjectSafetyToolInput(
                    dataset_version_id=original.dataset_version_id, subject_id="S1"
                ),
            ),
            "result": result,
        }
    )

    async def fake_plan(_session: AsyncSession, _plan_id: object) -> AnalysisPlanDetails:
        return plan

    async def fake_calculation(
        _session: AsyncSession, version_id: object, subject_id: str
    ) -> SubjectSafetySummary:
        assert version_id == plan.dataset_version_id
        assert subject_id == "S1"
        return SubjectSafetySummary(
            method_version="subject-safety-summary/1.0",
            unique_subject_id="S1",
            actual_arm="Placebo",
            age=55,
            age_unit="YEARS",
            sex="F",
            ae_event_count=0,
            severe_ae_event_count=0,
            serious_ae_event_count=0,
            lab_result_count=0,
            flagged_lab_count=0,
            events=(),
            flagged_labs=(),
        )

    monkeypatch.setattr("trialops.lineage.reproduction.get_analysis_plan", fake_plan)
    monkeypatch.setattr(
        "trialops.lineage.reproduction.get_stored_subject_safety_summary", fake_calculation
    )
    comparison = asyncio.run(reproduce_analysis_plan(cast(AsyncSession, object()), plan.id))
    assert comparison.status == "EXACT_MATCH"
