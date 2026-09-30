"""Application-controlled generation and numeric grounding of AI explanations."""

import re
from decimal import Decimal
from enum import StrEnum

from pydantic import ValidationError

from trialops.agent.interpretation_contracts import (
    GroundingStatus,
    InterpretationProposal,
    NumericFact,
    NumericFactName,
    VerifiedInterpretation,
)
from trialops.agent.interpretation_model import (
    InterpretationModel,
    InterpretationModelError,
    InterpretationModelRequest,
)
from trialops.analytics.contracts import AltAbnormalityResponse, SevereAeIncidenceResponse

PROMPT_VERSION = "alt-result-interpretation/1.0"
SEVERE_AE_PROMPT_VERSION = "severe-ae-result-interpretation/1.0"
_NUMBER_PATTERN = re.compile(r"(?<![\d.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d.])")


class InterpretationErrorCode(StrEnum):
    """Stable reasons an AI explanation could not be accepted."""

    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    INVALID_MODEL_RESPONSE = "INVALID_MODEL_RESPONSE"
    UNGROUNDED_NUMERIC_CLAIM = "UNGROUNDED_NUMERIC_CLAIM"


class InterpretationError(RuntimeError):
    """Safe failure that does not expose raw provider output."""

    def __init__(self, code: InterpretationErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def build_numeric_facts(
    result: AltAbnormalityResponse | SevereAeIncidenceResponse,
) -> tuple[NumericFact, ...]:
    """Select the aggregate numeric facts the model is permitted to cite."""
    if isinstance(result, SevereAeIncidenceResponse):
        facts: list[NumericFact] = [
            NumericFact(
                name="excluded_screen_failure_subjects",
                value=Decimal(result.excluded_screen_failure_subjects),
            )
        ]
        for index, arm in enumerate(result.arms, start=1):
            prefix = f"arm_{index}"
            facts.extend(
                (
                    NumericFact(
                        name=f"{prefix}_subjects_in_arm", value=Decimal(arm.subjects_in_arm)
                    ),
                    NumericFact(
                        name=f"{prefix}_subjects_with_severe_ae",
                        value=Decimal(arm.subjects_with_severe_ae),
                    ),
                    NumericFact(
                        name=f"{prefix}_severe_ae_event_count",
                        value=Decimal(arm.severe_ae_event_count),
                    ),
                    NumericFact(
                        name=f"{prefix}_incidence_percent",
                        value=arm.incidence_percent,
                    ),
                )
            )
        return tuple(facts)
    return (
        NumericFact(
            name=NumericFactName.THRESHOLD_MULTIPLIER,
            value=result.threshold_multiplier,
        ),
        NumericFact(name=NumericFactName.ALT_ROW_COUNT, value=Decimal(result.alt_row_count)),
        NumericFact(
            name=NumericFactName.ELIGIBLE_ROW_COUNT,
            value=Decimal(result.eligible_row_count),
        ),
        NumericFact(
            name=NumericFactName.EXCLUDED_ROW_COUNT,
            value=Decimal(result.excluded_row_count),
        ),
        NumericFact(
            name=NumericFactName.QUALIFYING_MEASUREMENT_COUNT,
            value=Decimal(result.qualifying_measurement_count),
        ),
        NumericFact(
            name=NumericFactName.SUBJECTS_WITH_QUALIFYING_MEASUREMENT,
            value=Decimal(result.subjects_with_qualifying_measurement),
        ),
    )


def _summary_numbers(summary: str, allowed_percentages: set[Decimal]) -> tuple[Decimal, ...]:
    """Extract ordinary decimal mentions and reject unsupported percentages."""
    values: list[Decimal] = []
    for match in _NUMBER_PATTERN.finditer(summary):
        suffix = summary[match.end() :].lstrip()
        value = Decimal(match.group().replace(",", ""))
        if suffix.startswith("%") and value not in allowed_percentages:
            raise InterpretationError(
                InterpretationErrorCode.UNGROUNDED_NUMERIC_CLAIM,
                "The interpretation contains a percentage that was not calculated.",
            )
        values.append(value)
    return tuple(values)


def verify_numeric_grounding(
    proposal: InterpretationProposal,
    allowed_facts: tuple[NumericFact, ...],
) -> None:
    """Require declared claims and prose numbers to match trusted result fields."""
    allowed_by_name = {fact.name: fact.value for fact in allowed_facts}
    for claim in proposal.numeric_claims:
        if allowed_by_name.get(claim.field) != claim.value:
            raise InterpretationError(
                InterpretationErrorCode.UNGROUNDED_NUMERIC_CLAIM,
                "The interpretation contains a numeric claim unsupported by the result.",
            )

    allowed_percentage_values = {
        claim.value
        for claim in proposal.numeric_claims
        if claim.field.endswith("_incidence_percent")
    }
    mentioned_values = set(_summary_numbers(proposal.summary, allowed_percentage_values))
    declared_values = {claim.value for claim in proposal.numeric_claims}
    if mentioned_values != declared_values:
        raise InterpretationError(
            InterpretationErrorCode.UNGROUNDED_NUMERIC_CLAIM,
            "The interpretation's prose and declared numeric claims do not match.",
        )


async def generate_grounded_interpretation(
    model: InterpretationModel,
    *,
    question: str,
    purpose: str,
    result: AltAbnormalityResponse | SevereAeIncidenceResponse,
) -> VerifiedInterpretation:
    """Request, validate, and numerically verify one AI explanation."""
    if not model.model_id.strip():
        raise InterpretationError(
            InterpretationErrorCode.MODEL_UNAVAILABLE,
            "The interpretation model is not configured with an identifier.",
        )

    numeric_facts = build_numeric_facts(result)
    is_severe_ae = isinstance(result, SevereAeIncidenceResponse)
    if isinstance(result, SevereAeIncidenceResponse):
        warnings: tuple[str, ...] = (result.population_definition,)
        group_labels = tuple(arm.arm for arm in result.arms)
    else:
        warnings = tuple(finding.message for finding in result.findings)
        group_labels = ()
    request = InterpretationModelRequest(
        question=question,
        purpose=purpose,
        method_version=result.method_version,
        numeric_facts=numeric_facts,
        warnings=warnings,
        timing_limitation=result.timing_limitation,
        group_labels=group_labels,
    )
    try:
        response_json = await model.generate_interpretation_json(request)
    except InterpretationModelError as exc:
        raise InterpretationError(
            InterpretationErrorCode.MODEL_UNAVAILABLE,
            "The interpretation model is temporarily unavailable.",
        ) from exc

    try:
        proposal = InterpretationProposal.model_validate_json(response_json)
    except ValidationError as exc:
        raise InterpretationError(
            InterpretationErrorCode.INVALID_MODEL_RESPONSE,
            "The interpretation model returned a response that violates the contract.",
        ) from exc

    verify_numeric_grounding(proposal, numeric_facts)
    return VerifiedInterpretation(
        summary=proposal.summary,
        numeric_claims=proposal.numeric_claims,
        grounding_status=GroundingStatus.NUMERICALLY_VERIFIED,
        prompt_version=SEVERE_AE_PROMPT_VERSION if is_severe_ae else PROMPT_VERSION,
        model_id=model.model_id,
    )
