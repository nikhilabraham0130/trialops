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
from trialops.analytics.contracts import AltAbnormalityResponse

PROMPT_VERSION = "alt-result-interpretation/1.0"
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


def build_numeric_facts(result: AltAbnormalityResponse) -> tuple[NumericFact, ...]:
    """Select the aggregate numeric facts the model is permitted to cite."""
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


def _summary_numbers(summary: str) -> tuple[Decimal, ...]:
    """Extract ordinary decimal mentions and reject unsupported percentages."""
    values: list[Decimal] = []
    for match in _NUMBER_PATTERN.finditer(summary):
        suffix = summary[match.end() :].lstrip()
        if suffix.startswith("%"):
            raise InterpretationError(
                InterpretationErrorCode.UNGROUNDED_NUMERIC_CLAIM,
                "The interpretation contains a percentage that was not calculated.",
            )
        values.append(Decimal(match.group().replace(",", "")))
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

    mentioned_values = set(_summary_numbers(proposal.summary))
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
    result: AltAbnormalityResponse,
) -> VerifiedInterpretation:
    """Request, validate, and numerically verify one AI explanation."""
    if not model.model_id.strip():
        raise InterpretationError(
            InterpretationErrorCode.MODEL_UNAVAILABLE,
            "The interpretation model is not configured with an identifier.",
        )

    numeric_facts = build_numeric_facts(result)
    request = InterpretationModelRequest(
        question=question,
        purpose=purpose,
        method_version=result.method_version,
        numeric_facts=numeric_facts,
        warnings=tuple(finding.message for finding in result.findings),
        timing_limitation=result.timing_limitation,
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
        prompt_version=PROMPT_VERSION,
        model_id=model.model_id,
    )
