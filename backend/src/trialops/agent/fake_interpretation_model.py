"""Deterministic interpretation-model substitute for tests and local demos."""

from trialops.agent.interpretation_model import (
    InterpretationModelError,
    InterpretationModelRequest,
)


class FakeInterpretationModel:
    """Return configured JSON while recording the aggregate context received."""

    def __init__(
        self,
        response_json: str,
        *,
        model_id: str = "fake-interpretation-model",
        error: InterpretationModelError | None = None,
    ) -> None:
        self.response_json = response_json
        self._model_id = model_id
        self.error = error
        self.requests: list[InterpretationModelRequest] = []

    @property
    def model_id(self) -> str:
        """Return the configured fake identifier for lineage tests."""
        return self._model_id

    async def generate_interpretation_json(self, request: InterpretationModelRequest) -> str:
        """Record the request, then return or fail deterministically."""
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response_json
