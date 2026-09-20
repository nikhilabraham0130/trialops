"""Least-privilege catalog supplied to the TrialOps language model."""

from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict

from trialops.agent.contracts import AltThresholdToolInput, ApprovedToolName


class ToolSpecification(BaseModel):
    """Model-facing description of one capability the application implements."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: ApprovedToolName
    description: str
    input_schema: dict[str, Any]
    requires_confirmation: bool


_TOOL_INPUT_MODELS: MappingProxyType[ApprovedToolName, type[BaseModel]] = MappingProxyType(
    {ApprovedToolName.CALCULATE_ALT_GT_3X_ULN: AltThresholdToolInput}
)

_TOOL_DESCRIPTIONS: MappingProxyType[ApprovedToolName, str] = MappingProxyType(
    {
        ApprovedToolName.CALCULATE_ALT_GT_3X_ULN: (
            "Calculate stored ALT measurements strictly above three times their upper reference "
            "limit for one immutable dataset version. Report measurements and distinct subjects "
            "separately. Do not describe unflagged measurements as post-baseline."
        )
    }
)


def get_approved_tool_specifications() -> tuple[ToolSpecification, ...]:
    """Return only implemented tools that the model is currently allowed to request."""
    return tuple(
        ToolSpecification(
            name=name,
            description=_TOOL_DESCRIPTIONS[name],
            input_schema=input_model.model_json_schema(),
            requires_confirmation=True,
        )
        for name, input_model in _TOOL_INPUT_MODELS.items()
    )
