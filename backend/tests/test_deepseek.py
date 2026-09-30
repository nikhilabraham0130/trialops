"""Tests for the live DeepSeek adapter without external network calls."""

import asyncio
import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from trialops.agent.deepseek import DeepSeekModelAdapter
from trialops.agent.interpretation_contracts import NumericFact, NumericFactName
from trialops.agent.interpretation_model import (
    InterpretationModelError,
    InterpretationModelRequest,
)
from trialops.agent.model import PlanModelError, PlanModelRequest
from trialops.agent.tools import get_approved_tool_specifications


def _adapter(handler: httpx.MockTransport) -> DeepSeekModelAdapter:
    return DeepSeekModelAdapter(
        api_key=SecretStr("test-secret-key"),
        base_url="https://provider.example/",
        model="deepseek-flash",
        transport=handler,
    )


def _completion(content: str | None, *, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "id": "completion-1",
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content},
            }
        ],
    }


def test_plan_request_uses_bearer_auth_json_mode_and_approved_tools() -> None:
    response_json = (
        '{"tool_name":"calculate_alt_gt_3x_uln",'
        '"purpose":"Use the approved deterministic calculation."}'
    )

    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://provider.example/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-secret-key"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-flash"
        assert body["response_format"] == {"type": "json_object"}
        assert body["max_tokens"] == 512
        prompt = json.loads(body["messages"][1]["content"])
        assert prompt["question"] == "Check ALT measurements."
        assert prompt["approved_tools"][0]["name"] == "calculate_alt_gt_3x_uln"
        assert "json" in body["messages"][0]["content"].lower()
        return httpx.Response(200, json=_completion(response_json))

    model = _adapter(httpx.MockTransport(respond))
    result = asyncio.run(
        model.generate_plan_json(
            PlanModelRequest(
                question="Check ALT measurements.",
                tools=get_approved_tool_specifications(),
            )
        )
    )

    assert result == response_json


def test_interpretation_request_sends_only_aggregate_context() -> None:
    response_json = (
        '{"summary":"There were 4 qualifying measurements.",'
        '"numeric_claims":[{"field":"qualifying_measurement_count","value":4}]}'
    )

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["max_tokens"] == 1024
        prompt = json.loads(body["messages"][1]["content"])
        assert prompt == {
            "group_labels": [],
            "method_version": "alt-gt-3x-uln/1.0",
            "numeric_facts": [{"name": "qualifying_measurement_count", "value": "4"}],
            "purpose": "Explain the deterministic result.",
            "question": "Were ALT measurements elevated?",
            "timing_limitation": "Treatment timing was not established.",
            "warnings": ["One row was excluded."],
        }
        assert "dataset_version_id" not in body["messages"][1]["content"]
        return httpx.Response(200, json=_completion(response_json))

    model = _adapter(httpx.MockTransport(respond))
    result = asyncio.run(
        model.generate_interpretation_json(
            InterpretationModelRequest(
                question="Were ALT measurements elevated?",
                purpose="Explain the deterministic result.",
                method_version="alt-gt-3x-uln/1.0",
                numeric_facts=(
                    NumericFact(
                        name=NumericFactName.QUALIFYING_MEASUREMENT_COUNT,
                        value=Decimal(4),
                    ),
                ),
                warnings=("One row was excluded.",),
                timing_limitation="Treatment timing was not established.",
            )
        )
    )

    assert model.model_id == "deepseek:deepseek-flash"
    assert result == response_json


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"error": {"message": "secret provider detail"}}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json=_completion("{}", finish_reason="length")),
        httpx.Response(200, json=_completion(None)),
        httpx.Response(200, json=_completion("   ")),
    ],
)
def test_plan_request_translates_provider_failures(response: httpx.Response) -> None:
    model = _adapter(httpx.MockTransport(lambda _request: response))

    with pytest.raises(PlanModelError) as raised:
        asyncio.run(
            model.generate_plan_json(
                PlanModelRequest(
                    question="Check ALT.",
                    tools=get_approved_tool_specifications(),
                )
            )
        )

    assert str(raised.value) == "DeepSeek planning request failed."
    assert "secret" not in str(raised.value)


def test_interpretation_request_translates_provider_failure() -> None:
    model = _adapter(httpx.MockTransport(lambda _request: httpx.Response(503)))
    request = InterpretationModelRequest(
        question="Check ALT.",
        purpose="Explain it.",
        method_version="alt-gt-3x-uln/1.0",
        numeric_facts=(),
        warnings=(),
        timing_limitation="Timing unavailable.",
    )

    with pytest.raises(InterpretationModelError) as raised:
        asyncio.run(model.generate_interpretation_json(request))

    assert str(raised.value) == "DeepSeek interpretation request failed."
