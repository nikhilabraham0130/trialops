"""Provider-neutral interface for models that propose analysis plans."""

from dataclasses import dataclass
from typing import Protocol

from trialops.agent.tools import ToolSpecification


@dataclass(frozen=True, slots=True)
class PlanModelRequest:
    """Minimum context a model receives when selecting an approved tool."""

    question: str
    tools: tuple[ToolSpecification, ...]


class PlanModelError(RuntimeError):
    """Raised by a provider adapter when it cannot return a model response."""


class PlanModel(Protocol):
    """Interface implemented by fake and future external model adapters."""

    async def generate_plan_json(self, request: PlanModelRequest) -> str:
        """Return one raw JSON proposal for central validation."""
        ...
