"""Provider-neutral contract for structured AI routing evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class DecisionTask(StrEnum):
    """Only AI decision tasks permitted in Gheras V1."""

    MODERATION = "moderation"
    CLASSIFICATION = "classification"


@dataclass(frozen=True, slots=True)
class StructuredDecisionRequest:
    """One routing-only model request with user content kept as data."""

    task: DecisionTask
    instruction_version: str
    instructions: tuple[str, ...]
    text: str | None
    media: dict[str, Any] | None
    allowed_output_keys: tuple[str, ...]


class StructuredDecisionClient(Protocol):
    """Injected model client; concrete provider/network clients live behind this boundary."""

    async def request(self, request: StructuredDecisionRequest) -> object:
        """Return one provider-decoded structured value without taking external action."""
        ...
