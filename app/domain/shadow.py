"""Side-effect-free shadow evaluation domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.classification import ClassificationRoute
from app.domain.events import Platform
from app.domain.publishing import PublicationSourceKind


class ShadowOutcome(StrEnum):
    """Normalized outcome produced without taking any external action."""

    WOULD_PUBLISH = "would_publish"
    WOULD_WAIT_HUMAN = "would_wait_human"
    WOULD_ROUTE_FATWA = "would_route_fatwa"
    NOT_READY = "not_ready"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ShadowDecision:
    """One deterministic, side-effect-free observation before persistence."""

    event_id: str
    correlation_id: str
    platform: Platform
    evaluator_version: str
    observed_route: ClassificationRoute | None
    outcome: ShadowOutcome
    source_kind: PublicationSourceKind | None = None
    evidence_id: str | None = None
    proposed_text: str | None = None

    def __post_init__(self) -> None:
        version = self.evaluator_version.strip()
        if not version or len(version) > 80 or any(char.isspace() for char in version):
            raise ValueError("evaluator_version must be a compact identifier up to 80 characters")
        if not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty")

        publish_fields = (self.source_kind, self.evidence_id, self.proposed_text)
        if self.outcome is ShadowOutcome.WOULD_PUBLISH:
            if any(value is None for value in publish_fields):
                raise ValueError("would_publish requires exact source evidence and text")
            assert self.evidence_id is not None
            assert self.proposed_text is not None
            if not self.evidence_id.strip() or not self.proposed_text.strip():
                raise ValueError("would_publish evidence and text must not be empty")
        elif any(value is not None for value in publish_fields):
            raise ValueError("non-publish shadow outcomes cannot carry publishable content")


@dataclass(frozen=True, slots=True)
class ShadowEvaluation:
    """Persisted immutable shadow audit result."""

    id: str
    event_id: str
    correlation_id: str
    platform: Platform
    evaluator_version: str
    observed_route: ClassificationRoute | None
    outcome: ShadowOutcome
    source_kind: PublicationSourceKind | None
    evidence_id: str | None
    proposed_text: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ShadowSummary:
    """Aggregate shadow metrics that expose no user message content."""

    total_evaluated: int
    by_platform: dict[str, int]
    by_route: dict[str, int]
    by_outcome: dict[str, int]
    publishable: int
    non_publishable: int
