"""Provider-neutral contract for drafting, but never executing, clinical SQL."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SQLModelRequest:
    question: str
    approved_schema: dict[str, tuple[str, ...]]


class SQLModelError(RuntimeError):
    """The provider could not return a complete SQL proposal."""


@runtime_checkable
class SQLModel(Protocol):
    async def generate_sql_json(self, request: SQLModelRequest) -> str:
        """Return raw JSON to be validated by trusted application code."""
        ...
