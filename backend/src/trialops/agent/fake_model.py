"""Deterministic model substitute for orchestration tests and local demos."""

from trialops.agent.model import PlanModelError, PlanModelRequest


class FakePlanModel:
    """Return configured JSON while recording exactly what the model received."""

    def __init__(self, response_json: str, *, error: PlanModelError | None = None) -> None:
        self.response_json = response_json
        self.error = error
        self.requests: list[PlanModelRequest] = []

    async def generate_plan_json(self, request: PlanModelRequest) -> str:
        """Record the request, then return or fail in a deterministic way."""
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response_json
