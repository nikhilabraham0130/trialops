"""Tests for AI interpretation contracts and deterministic numeric grounding."""

import asyncio
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from trialops.agent.fake_interpretation_model import FakeInterpretationModel
from trialops.agent.interpretation import (
    PROMPT_VERSION,
    SERIOUS_AE_PROMPT_VERSION,
    SEVERE_AE_PROMPT_VERSION,
    SUBJECT_SAFETY_PROMPT_VERSION,
    InterpretationError,
    InterpretationErrorCode,
    build_numeric_facts,
    generate_grounded_interpretation,
)
from trialops.agent.interpretation_contracts import (
    GroundingStatus,
    NumericClaim,
    NumericFactName,
)
from trialops.agent.interpretation_model import InterpretationModelError
from trialops.analytics.contracts import (
    AltAbnormalityResponse,
    SeriousAeArmResponse,
    SeriousAeIncidenceResponse,
    SevereAeArmResponse,
    SevereAeIncidenceResponse,
    SubjectSafetySummaryResponse,
    ValidationFindingResponse,
)
from trialops.validation.findings import FindingSeverity


def _result() -> AltAbnormalityResponse:
    return AltAbnormalityResponse(
        dataset_version_id=UUID("00000000-0000-0000-0000-000000000001"),
        method_version="alt-gt-3x-uln/1.0",
        threshold_multiplier=Decimal(3),
        alt_row_count=1814,
        eligible_row_count=1814,
        excluded_row_count=0,
        qualifying_measurement_count=4,
        subjects_with_qualifying_measurement=3,
        exceedances=(),
        findings=(
            ValidationFindingResponse(
                rule_code="EXAMPLE_WARNING",
                severity=FindingSeverity.WARNING,
                domain="LB",
                source_record_number=99,
                message="One example warning was retained.",
            ),
        ),
        timing_limitation="A blank baseline flag does not prove post-treatment timing.",
    )


def _severe_result() -> SevereAeIncidenceResponse:
    return SevereAeIncidenceResponse(
        dataset_version_id=UUID("00000000-0000-0000-0000-000000000001"),
        method_version="severe-ae-incidence/1.0",
        excluded_screen_failure_subjects=2,
        population_definition="All DM subjects grouped by ACTARM.",
        timing_limitation="Treatment emergence was not established.",
        arms=(
            SevereAeArmResponse(
                arm="Placebo",
                subjects_in_arm=3,
                subjects_with_severe_ae=1,
                severe_ae_event_count=2,
                incidence_percent=Decimal("33.33"),
            ),
        ),
        evidence=(),
    )


VALID_RESPONSE = """{
  "summary": "Among 1,814 eligible ALT measurements, 4 exceeded 3 times ULN across 3 subjects.",
  "numeric_claims": [
    {"field": "eligible_row_count", "value": 1814},
    {"field": "qualifying_measurement_count", "value": 4},
    {"field": "threshold_multiplier", "value": 3},
    {"field": "subjects_with_qualifying_measurement", "value": 3}
  ]
}"""


def test_subject_interpretation_uses_only_aggregate_counts_not_source_rows() -> None:
    result = SubjectSafetySummaryResponse(
        dataset_version_id=UUID("00000000-0000-0000-0000-000000000001"),
        method_version="subject-safety-summary/1.0",
        unique_subject_id="S1",
        actual_arm="Placebo",
        age=55,
        age_unit="YEARS",
        sex="F",
        ae_event_count=3,
        severe_ae_event_count=1,
        serious_ae_event_count=0,
        lab_result_count=10,
        flagged_lab_count=2,
        events=(),
        flagged_labs=(),
        interpretation_limit="These are source classifications, not diagnoses.",
    )
    model = FakeInterpretationModel(
        '{"summary":"The subject had 3 AE events and 2 source-flagged labs.",'
        '"numeric_claims":['
        '{"field":"ae_event_count","value":3},'
        '{"field":"flagged_lab_count","value":2}]}'
    )
    verified = asyncio.run(
        generate_grounded_interpretation(
            model,
            question="Summarize S1.",
            purpose="Show source records.",
            result=result,
        )
    )
    assert verified.prompt_version == SUBJECT_SAFETY_PROMPT_VERSION
    assert {fact.name for fact in model.requests[0].numeric_facts} == {
        "ae_event_count",
        "severe_ae_event_count",
        "serious_ae_event_count",
        "lab_result_count",
        "flagged_lab_count",
    }
    assert model.requests[0].group_labels == ()
    assert model.requests[0].warnings == ("These are source classifications, not diagnoses.",)


def test_numeric_fact_catalog_uses_only_aggregate_result_fields() -> None:
    facts = build_numeric_facts(_result())

    assert {fact.name: fact.value for fact in facts} == {
        NumericFactName.THRESHOLD_MULTIPLIER: Decimal(3),
        NumericFactName.ALT_ROW_COUNT: Decimal(1814),
        NumericFactName.ELIGIBLE_ROW_COUNT: Decimal(1814),
        NumericFactName.EXCLUDED_ROW_COUNT: Decimal(0),
        NumericFactName.QUALIFYING_MEASUREMENT_COUNT: Decimal(4),
        NumericFactName.SUBJECTS_WITH_QUALIFYING_MEASUREMENT: Decimal(3),
    }


def test_severe_ae_interpretation_uses_only_backend_aggregate_counts_and_percentages() -> None:
    model = FakeInterpretationModel(
        '{"summary":"In Placebo, 1 of 3 subjects had a severe AE (33.33%), with 2 events.",'
        '"numeric_claims":['
        '{"field":"arm_1_subjects_with_severe_ae","value":1},'
        '{"field":"arm_1_subjects_in_arm","value":3},'
        '{"field":"arm_1_incidence_percent","value":"33.33"},'
        '{"field":"arm_1_severe_ae_event_count","value":2}]}'
    )

    verified = asyncio.run(
        generate_grounded_interpretation(
            model,
            question="Compare recorded severe AEs.",
            purpose="Summarize by arm.",
            result=_severe_result(),
        )
    )

    assert verified.prompt_version == SEVERE_AE_PROMPT_VERSION
    request = model.requests[0]
    assert request.group_labels == ("Placebo",)
    assert request.warnings == ("All DM subjects grouped by ACTARM.",)
    assert {fact.name: fact.value for fact in request.numeric_facts} == {
        "excluded_screen_failure_subjects": Decimal(2),
        "arm_1_subjects_in_arm": Decimal(3),
        "arm_1_subjects_with_severe_ae": Decimal(1),
        "arm_1_severe_ae_event_count": Decimal(2),
        "arm_1_incidence_percent": Decimal("33.33"),
    }


def test_severe_ae_interpretation_rejects_an_uncomputed_percentage() -> None:
    model = FakeInterpretationModel(
        '{"summary":"In Placebo, 20% of subjects had a severe AE.",'
        '"numeric_claims":[{"field":"arm_1_incidence_percent","value":20}]}'
    )

    with pytest.raises(InterpretationError) as raised:
        asyncio.run(
            generate_grounded_interpretation(
                model,
                question="Compare recorded severe AEs.",
                purpose="Summarize by arm.",
                result=_severe_result(),
            )
        )
    assert raised.value.code is InterpretationErrorCode.UNGROUNDED_NUMERIC_CLAIM


def test_serious_ae_interpretation_uses_serious_counts_and_timing_warning() -> None:
    result = SeriousAeIncidenceResponse(
        dataset_version_id=UUID("00000000-0000-0000-0000-000000000001"),
        method_version="serious-ae-incidence/1.0",
        excluded_screen_failure_subjects=2,
        population_definition="DM subjects grouped by ACTARM.",
        timing_limitation="Not confirmed treatment-emergent.",
        arms=(
            SeriousAeArmResponse(
                arm="Placebo",
                subjects_in_arm=3,
                subjects_with_serious_ae=1,
                serious_ae_event_count=2,
                incidence_percent=Decimal("33.33"),
            ),
        ),
        evidence=(),
    )
    model = FakeInterpretationModel(
        '{"summary":"In Placebo, 1 of 3 subjects had a serious AE (33.33%), with 2 events.",'
        '"numeric_claims":['
        '{"field":"arm_1_subjects_with_serious_ae","value":1},'
        '{"field":"arm_1_subjects_in_arm","value":3},'
        '{"field":"arm_1_incidence_percent","value":"33.33"},'
        '{"field":"arm_1_serious_ae_event_count","value":2}]}'
    )
    verified = asyncio.run(
        generate_grounded_interpretation(
            model,
            question="Compare recorded serious AEs.",
            purpose="Summarize by arm.",
            result=result,
        )
    )
    assert verified.prompt_version == SERIOUS_AE_PROMPT_VERSION
    request = model.requests[0]
    assert request.timing_limitation == "Not confirmed treatment-emergent."
    assert {fact.name for fact in request.numeric_facts} == {
        "excluded_screen_failure_subjects",
        "arm_1_subjects_in_arm",
        "arm_1_subjects_with_serious_ae",
        "arm_1_serious_ae_event_count",
        "arm_1_incidence_percent",
    }


def test_numeric_claim_rejects_nonfinite_value() -> None:
    with pytest.raises(ValidationError):
        NumericClaim(
            field=NumericFactName.QUALIFYING_MEASUREMENT_COUNT,
            value=Decimal("NaN"),
        )


def test_interpretation_receives_minimum_context_and_accepts_supported_numbers() -> None:
    model = FakeInterpretationModel(VALID_RESPONSE, model_id="fake-model-v1")

    interpretation = asyncio.run(
        generate_grounded_interpretation(
            model,
            question="Were any ALT measurements elevated?",
            purpose="Explain the approved ALT calculation.",
            result=_result(),
        )
    )

    assert interpretation.grounding_status is GroundingStatus.NUMERICALLY_VERIFIED
    assert interpretation.prompt_version == PROMPT_VERSION
    assert interpretation.model_id == "fake-model-v1"
    assert interpretation.summary.startswith("Among 1,814")
    assert len(model.requests) == 1
    request = model.requests[0]
    assert request.question == "Were any ALT measurements elevated?"
    assert request.method_version == "alt-gt-3x-uln/1.0"
    assert request.warnings == ("One example warning was retained.",)
    assert not hasattr(request, "dataset_version_id")
    assert not hasattr(request, "exceedances")


def test_interpretation_may_use_no_numbers_when_it_declares_no_claims() -> None:
    model = FakeInterpretationModel(
        '{"summary":"The stored calculation completed.","numeric_claims":[]}'
    )

    interpretation = asyncio.run(
        generate_grounded_interpretation(
            model,
            question="Explain the result.",
            purpose="Provide a restrained explanation.",
            result=_result(),
        )
    )

    assert interpretation.numeric_claims == ()


@pytest.mark.parametrize(
    "response_json",
    [
        (
            '{"summary":"There were 14 qualifying measurements.",'
            '"numeric_claims":[{"field":"qualifying_measurement_count","value":14}]}'
        ),
        (
            '{"summary":"There were 4 qualifying measurements and 14 total.",'
            '"numeric_claims":[{"field":"qualifying_measurement_count","value":4}]}'
        ),
        (
            '{"summary":"There were 4 qualifying measurements.",'
            '"numeric_claims":['
            '{"field":"qualifying_measurement_count","value":4},'
            '{"field":"threshold_multiplier","value":3}]}'
        ),
        (
            '{"summary":"Four measurements represented 4% of the result.",'
            '"numeric_claims":[{"field":"qualifying_measurement_count","value":4}]}'
        ),
    ],
)
def test_interpretation_rejects_unsupported_undeclared_unused_and_percentage_numbers(
    response_json: str,
) -> None:
    model = FakeInterpretationModel(response_json)

    with pytest.raises(InterpretationError) as raised:
        asyncio.run(
            generate_grounded_interpretation(
                model,
                question="Explain the result.",
                purpose="Provide a restrained explanation.",
                result=_result(),
            )
        )

    assert raised.value.code is InterpretationErrorCode.UNGROUNDED_NUMERIC_CLAIM


@pytest.mark.parametrize(
    "response_json",
    [
        "not json",
        '{"summary":"   ","numeric_claims":[]}',
        '{"summary":"No numeric claims.","numeric_claims":[],"extra":true}',
        (
            '{"summary":"4 measurements.","numeric_claims":['
            '{"field":"qualifying_measurement_count","value":4},'
            '{"field":"qualifying_measurement_count","value":4}]}'
        ),
        (
            '{"summary":"A result was reported.","numeric_claims":['
            '{"field":"qualifying_measurement_count","value":"NaN"}]}'
        ),
    ],
)
def test_interpretation_rejects_invalid_model_contract(response_json: str) -> None:
    model = FakeInterpretationModel(response_json)

    with pytest.raises(InterpretationError) as raised:
        asyncio.run(
            generate_grounded_interpretation(
                model,
                question="Explain the result.",
                purpose="Provide a restrained explanation.",
                result=_result(),
            )
        )

    assert raised.value.code is InterpretationErrorCode.INVALID_MODEL_RESPONSE


def test_interpretation_maps_provider_failure_without_leaking_details() -> None:
    model = FakeInterpretationModel(
        VALID_RESPONSE,
        error=InterpretationModelError("provider secret"),
    )

    with pytest.raises(InterpretationError) as raised:
        asyncio.run(
            generate_grounded_interpretation(
                model,
                question="Explain the result.",
                purpose="Provide a restrained explanation.",
                result=_result(),
            )
        )

    assert raised.value.code is InterpretationErrorCode.MODEL_UNAVAILABLE
    assert "secret" not in str(raised.value)
    assert raised.value.__cause__ is not None


def test_interpretation_requires_model_identifier_for_lineage() -> None:
    model = FakeInterpretationModel(VALID_RESPONSE, model_id="   ")

    with pytest.raises(InterpretationError) as raised:
        asyncio.run(
            generate_grounded_interpretation(
                model,
                question="Explain the result.",
                purpose="Provide a restrained explanation.",
                result=_result(),
            )
        )

    assert raised.value.code is InterpretationErrorCode.MODEL_UNAVAILABLE
    assert model.requests == []
