"""Rerun a stored deterministic tool and compare its structured output."""

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.agent.contracts import ApprovedToolName, PlanStatus, SubjectSafetyToolInput
from trialops.agent.queries import get_analysis_plan
from trialops.analytics.contracts import (
    AltAbnormalityResponse,
    SevereAeIncidenceResponse,
    SubjectSafetySummaryResponse,
    to_alt_abnormality_response,
    to_severe_ae_incidence_response,
    to_subject_safety_summary_response,
)
from trialops.analytics.lab_abnormalities import calculate_stored_alt_gt_3x_uln
from trialops.analytics.severe_adverse_events import calculate_stored_severe_ae_incidence
from trialops.analytics.subject_safety import (
    SubjectNotFoundError,
    get_stored_subject_safety_summary,
)
from trialops.validation.alt import DatasetVersionNotFoundError

MAX_DISPLAYED_DIFFERENCES = 50


class ReproductionErrorCode(StrEnum):
    PLAN_NOT_EXECUTED = "PLAN_NOT_EXECUTED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class ReproductionError(RuntimeError):
    def __init__(self, code: ReproductionErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class FieldDifference(BaseModel):
    """One path whose canonical JSON values differ between two runs."""

    path: str
    stored: Any
    reproduced: Any


class ReproductionComparison(BaseModel):
    """On-demand comparison; no new analysis or approval is implied."""

    plan_id: UUID
    dataset_version_id: UUID
    tool_name: ApprovedToolName
    status: Literal["EXACT_MATCH", "MISMATCH"]
    stored_result_sha256: str
    reproduced_result_sha256: str
    difference_count: int
    differences: tuple[FieldDifference, ...]
    differences_truncated: bool


class StoredReproductionRun(ReproductionComparison):
    """A comparison retained in PostgreSQL for later inspection."""

    id: UUID
    created_at: datetime


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def compare_structured_results(
    *,
    plan_id: UUID,
    dataset_version_id: UUID,
    tool_name: ApprovedToolName,
    stored: BaseModel,
    reproduced: BaseModel,
) -> ReproductionComparison:
    """Compare every field, including source evidence, using canonical JSON."""
    stored_json = stored.model_dump(mode="json")
    reproduced_json = reproduced.model_dump(mode="json")
    differences: list[FieldDifference] = []
    difference_count = 0

    def walk(left: Any, right: Any, path: str) -> None:
        nonlocal difference_count
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(left.keys() | right.keys()):
                walk(left.get(key), right.get(key), f"{path}.{key}" if path else key)
            return
        if isinstance(left, list) and isinstance(right, list):
            for index in range(max(len(left), len(right))):
                left_item = left[index] if index < len(left) else None
                right_item = right[index] if index < len(right) else None
                walk(left_item, right_item, f"{path}[{index}]")
            return
        if left != right:
            difference_count += 1
            if len(differences) < MAX_DISPLAYED_DIFFERENCES:
                differences.append(FieldDifference(path=path, stored=left, reproduced=right))

    walk(stored_json, reproduced_json, "")
    stored_hash = hashlib.sha256(_canonical_bytes(stored_json)).hexdigest()
    reproduced_hash = hashlib.sha256(_canonical_bytes(reproduced_json)).hexdigest()
    return ReproductionComparison(
        plan_id=plan_id,
        dataset_version_id=dataset_version_id,
        tool_name=tool_name,
        status="EXACT_MATCH" if difference_count == 0 else "MISMATCH",
        stored_result_sha256=stored_hash,
        reproduced_result_sha256=reproduced_hash,
        difference_count=difference_count,
        differences=tuple(differences),
        differences_truncated=difference_count > MAX_DISPLAYED_DIFFERENCES,
    )


async def reproduce_analysis_plan(session: AsyncSession, plan_id: UUID) -> ReproductionComparison:
    """Use only the stored version and parameters, never new browser inputs."""
    plan = await get_analysis_plan(session, plan_id)
    if plan.status is not PlanStatus.EXECUTED or plan.result is None:
        raise ReproductionError(
            ReproductionErrorCode.PLAN_NOT_EXECUTED,
            "Only an executed plan can be reproduced.",
        )

    version_id = plan.dataset_version_id
    try:
        reproduced: (
            AltAbnormalityResponse | SevereAeIncidenceResponse | SubjectSafetySummaryResponse
        )
        if plan.tool_call.name is ApprovedToolName.CALCULATE_ALT_GT_3X_ULN:
            alt_result = await calculate_stored_alt_gt_3x_uln(session, version_id)
            reproduced = to_alt_abnormality_response(version_id, alt_result)
        elif plan.tool_call.name is ApprovedToolName.COMPARE_SEVERE_AE_INCIDENCE:
            severe_result = await calculate_stored_severe_ae_incidence(session, version_id)
            reproduced = to_severe_ae_incidence_response(version_id, severe_result)
        elif plan.tool_call.name is ApprovedToolName.GET_SUBJECT_SAFETY_SUMMARY and isinstance(
            plan.tool_call.arguments, SubjectSafetyToolInput
        ):
            subject_result = await get_stored_subject_safety_summary(
                session, version_id, plan.tool_call.arguments.subject_id
            )
            reproduced = to_subject_safety_summary_response(version_id, subject_result)
        else:
            raise ReproductionError(
                ReproductionErrorCode.SOURCE_UNAVAILABLE,
                "The saved tool cannot be reproduced with the current application.",
            )
    except (DatasetVersionNotFoundError, SubjectNotFoundError) as exc:
        raise ReproductionError(
            ReproductionErrorCode.SOURCE_UNAVAILABLE,
            "The saved analysis source is no longer available.",
        ) from exc

    return compare_structured_results(
        plan_id=plan_id,
        dataset_version_id=version_id,
        tool_name=plan.tool_call.name,
        stored=plan.result,
        reproduced=reproduced,
    )
