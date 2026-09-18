"""Structured, machine-readable validation findings."""

from dataclasses import dataclass
from enum import StrEnum


class FindingSeverity(StrEnum):
    """How a validation finding affects a specific intended use."""

    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    """One failed rule tied to a domain and, when possible, a source row."""

    rule_code: str
    severity: FindingSeverity
    domain: str
    source_record_number: int | None
    message: str
