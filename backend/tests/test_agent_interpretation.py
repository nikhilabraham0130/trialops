"""Tests for AI interpretation contracts and deterministic numeric grounding."""

import asyncio
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from trialops.agent.fake_interpretation_model import FakeInterpretationModel
from trialops.agent.interpretation import (
    PROMPT_VERSION,
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


VALID_RESPONSE = """{
  "summary": "Among 1,814 eligible ALT measurements, 4 exceeded 3 times ULN across 3 subjects.",
  "numeric_claims": [
    {"field": "eligible_row_count", "value": 1814},
    {"field": "qualifying_measurement_count", "value": 4},
    {"field": "threshold_multiplier", "value": 3},
    {"field": "subjects_with_qualifying_measurement", "value": 3}
  ]
}"""


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
