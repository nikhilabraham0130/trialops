"""Provider-neutral interface for models that explain structured results."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from trialops.agent.interpretation_contracts import NumericFact


@dataclass(frozen=True, slots=True)
class InterpretationModelRequest:
    """Minimum aggregate context supplied for a plain-language explanation."""

    question: str
    purpose: str
    method_version: str
    numeric_facts: tuple[NumericFact, ...]
    warnings: tuple[str, ...]
    timing_limitation: str


class InterpretationModelError(RuntimeError):
    """Raised when a provider cannot return an interpretation proposal."""


@runtime_checkable
class InterpretationModel(Protocol):
    """Interface implemented by fake and future external model adapters."""

    @property
    def model_id(self) -> str:
        """Return the provider's stable model identifier for lineage."""
        ...

    async def generate_interpretation_json(self, request: InterpretationModelRequest) -> str:
        """Return raw proposal JSON for central validation and grounding."""
        ...
