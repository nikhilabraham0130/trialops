"""DeepSeek adapter for TrialOps' provider-neutral model interfaces."""

import json
from typing import Annotated, Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from trialops.agent.interpretation_model import (
    InterpretationModelError,
    InterpretationModelRequest,
)
from trialops.agent.model import PlanModelError, PlanModelRequest
from trialops.sql.model import SQLModelError, SQLModelRequest

_PLAN_SYSTEM_PROMPT = """You select one approved TrialOps analysis tool only when it directly
answers the user's question. If no listed tool can answer it, return tool_name "unsupported".
Return JSON only, using exactly this shape:
{"tool_name":"approved or unsupported","purpose":"why","subject_id":null,"lab_test_code":null}
For get_subject_safety_summary, copy the exact USUBJID from the question into subject_id.
If no exact subject identifier is present, return unsupported with subject_id null.
For check_lab_reference_range, copy the exact LBTESTCD from the question into
lab_test_code (uppercase). If the question does not name a test code, return
unsupported. For every other tool, lab_test_code must be null.
For every other tool, subject_id must be null. Never invent an identifier.
Do not add other arguments, dataset identifiers, markdown, or unapproved tools.
Do not equate AESEV = SEVERE with seriousness, CTCAE grades, or treatment emergence.
The purpose must describe why the selected tool answers the question, or why it is unsupported.
"""

_INTERPRETATION_SYSTEM_PROMPT = """You explain a trusted clinical-analysis result.
Return JSON only, using exactly this shape:
{"summary":"restrained explanation","numeric_claims":[{"field":"fact name","value":0}]}
Use only the supplied aggregate facts. Every number written in the summary must appear in
numeric_claims with its exact field and value. Mention percentages only when they are supplied
as numeric facts. Do not make causal, diagnostic, treatment-emergent, or statistical-significance
claims.
"""

_SQL_SYSTEM_PROMPT = """Draft one simple PostgreSQL SELECT for a clinical question.
Return JSON only: {"candidate_sql":"SELECT ... or null","purpose":"brief explanation"}.
Use exactly one approved view and only its listed columns. You may use COUNT, SUM,
AVG, MIN, or MAX, filters, grouping, ordering, and LIMIT up to 100. No joins,
subqueries, arbitrary functions, table aliases, or internal tables. If the
question needs a join, an unavailable field, a clinical inference, or cannot be
answered by one approved view, set candidate_sql to null. Never assume
severity means seriousness or treatment emergence. Do not execute SQL.
"""


class _DeepSeekMessage(BaseModel):
    """Assistant message fields used by the adapter."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    content: str | None


class _DeepSeekChoice(BaseModel):
    """One completion candidate returned by DeepSeek."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    finish_reason: str
    message: _DeepSeekMessage


class _DeepSeekResponse(BaseModel):
    """Minimum provider envelope required to recover generated JSON."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    choices: Annotated[tuple[_DeepSeekChoice, ...], Field(min_length=1)]


class _DeepSeekRequestError(RuntimeError):
    """Internal provider failure translated into the public model protocols."""


class DeepSeekModelAdapter:
    """Generate strict JSON through DeepSeek without exposing provider details upstream."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str,
        model: str,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @property
    def model_id(self) -> str:
        """Identify the provider and configured model in interpretation lineage."""
        return f"deepseek:{self._model}"

    async def _generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> str:
        request_body: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key.get_secret_value()}",
                        "Content-Type": "application/json",
                    },
                    json=request_body,
                )
                response.raise_for_status()
                provider_response = _DeepSeekResponse.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise _DeepSeekRequestError("DeepSeek did not return a valid completion.") from exc

        choice = provider_response.choices[0]
        if choice.finish_reason != "stop" or not choice.message.content:
            raise _DeepSeekRequestError("DeepSeek returned an incomplete completion.")
        content = choice.message.content.strip()
        if not content:
            raise _DeepSeekRequestError("DeepSeek returned an empty completion.")
        return content

    async def generate_plan_json(self, request: PlanModelRequest) -> str:
        """Ask DeepSeek to select from the application-supplied tool catalog."""
        tool_catalog = [tool.model_dump(mode="json") for tool in request.tools]
        user_prompt = json.dumps(
            {
                "question": request.question,
                "approved_tools": tool_catalog,
            },
            sort_keys=True,
        )
        try:
            return await self._generate_json(
                system_prompt=_PLAN_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=512,
            )
        except _DeepSeekRequestError as exc:
            raise PlanModelError("DeepSeek planning request failed.") from exc

    async def generate_interpretation_json(self, request: InterpretationModelRequest) -> str:
        """Ask DeepSeek to explain only the supplied aggregate deterministic facts."""
        user_prompt = json.dumps(
            {
                "question": request.question,
                "purpose": request.purpose,
                "method_version": request.method_version,
                "numeric_facts": [
                    {"name": fact.name, "value": str(fact.value)} for fact in request.numeric_facts
                ],
                "warnings": request.warnings,
                "timing_limitation": request.timing_limitation,
                "group_labels": request.group_labels,
            },
            sort_keys=True,
        )
        try:
            return await self._generate_json(
                system_prompt=_INTERPRETATION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=1024,
            )
        except _DeepSeekRequestError as exc:
            raise InterpretationModelError("DeepSeek interpretation request failed.") from exc

    async def generate_sql_json(self, request: SQLModelRequest) -> str:
        """Draft SQL against only the application-supplied curated schema."""
        user_prompt = json.dumps(
            {"question": request.question, "approved_schema": request.approved_schema},
            sort_keys=True,
        )
        try:
            return await self._generate_json(
                system_prompt=_SQL_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=512,
            )
        except _DeepSeekRequestError as exc:
            raise SQLModelError("DeepSeek SQL planning request failed.") from exc
