"""Provider-neutral routing-classification domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.domain.events import Platform


class ClassificationRoute(StrEnum):
    """Only semantic routing destinations allowed in Gheras V1."""

    FAQ = "FAQ"
    SUPERVISOR = "SUPERVISOR"
    FATWA = "FATWA"


class ClassificationReason(StrEnum):
    """Machine-readable reasons for a deterministic local routing decision."""

    CONFIDENT_FAQ = "confident_faq"
    LOW_CONFIDENCE = "low_confidence"
    FAQ_KEY_MISSING = "faq_key_missing"
    RELIGIOUS_SAFETY_OVERRIDE = "religious_safety_override"
    EXPLICIT_FATWA = "explicit_fatwa"
    EXPLICIT_SUPERVISOR = "explicit_supervisor"
    ADAPTER_FAILURE = "adapter_failure"
    INVALID_ASSESSMENT = "invalid_assessment"
    NO_CLASSIFIABLE_TEXT = "no_classifiable_text"


@dataclass(frozen=True, slots=True)
class ClassificationRequest:
    """Normalized classifier input derived from an already moderated event."""

    event_id: str
    platform: Platform
    text: str | None
    media: dict[str, Any] | None

    @property
    def has_text(self) -> bool:
        return bool(self.text and self.text.strip())


@dataclass(frozen=True, slots=True)
class ClassificationAssessment:
    """Structured routing evidence returned by a classifier adapter."""

    proposed_route: ClassificationRoute
    confidence: float
    religious_possible: bool
    faq_key: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("classification confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ClassificationDecision:
    """Deterministic local decision after applying Gheras safety policy."""

    route: ClassificationRoute
    reasons: tuple[ClassificationReason, ...]
    faq_key: str | None = None

    def __post_init__(self) -> None:
        if not self.reasons:
            raise ValueError("classification decision must contain at least one reason")
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("classification reasons must not contain duplicates")
        if self.route is ClassificationRoute.FAQ and self.faq_key is None:
            raise ValueError("FAQ classification decision requires faq_key")
        if self.route is not ClassificationRoute.FAQ and self.faq_key is not None:
            raise ValueError("non-FAQ classification decision must not contain faq_key")


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Persisted semantic routing result for one durable inbound event."""

    id: str
    event_id: str
    route: ClassificationRoute
    reasons: tuple[ClassificationReason, ...]
    faq_key: str | None
    religious_possible: bool | None
    confidence: float | None
    adapter_name: str
    adapter_version: str
    created_at: datetime
