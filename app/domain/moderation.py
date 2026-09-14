"""Platform-neutral moderation domain models and deterministic policy decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.domain.events import Platform


class ModerationDisposition(StrEnum):
    """Routing-only outcome of moderation; never an external platform action."""

    ALLOW_ROUTING = "allow_routing"
    HUMAN_REVIEW = "human_review"
    BLOCK_ROUTING = "block_routing"


class ModerationVerdict(StrEnum):
    """Normalized adapter verdict before local policy is applied."""

    SAFE = "safe"
    UNSAFE = "unsafe"
    UNCERTAIN = "uncertain"


class ModerationSeverity(StrEnum):
    """Normalized severity supplied by a moderation adapter."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class ModerationCategory(StrEnum):
    """Provider-neutral content categories relevant to V1 moderation."""

    ABUSE = "abuse"
    HARMFUL_CONTENT = "harmful_content"
    VIOLENCE = "violence"
    SEXUAL_CONTENT = "sexual_content"
    SELF_HARM = "self_harm"
    SPAM = "spam"
    OTHER = "other"


class ModerationReason(StrEnum):
    """Machine-readable reasons explaining the local moderation disposition."""

    EXPLICIT_SAFE = "explicit_safe"
    EXPLICIT_UNSAFE = "explicit_unsafe"
    LOW_CONFIDENCE = "low_confidence"
    UNCERTAIN_VERDICT = "uncertain_verdict"
    TEXT_UNASSESSED = "text_unassessed"
    MEDIA_UNASSESSED = "media_unassessed"
    NO_ASSESSABLE_CONTENT = "no_assessable_content"
    ADAPTER_FAILURE = "adapter_failure"
    INVALID_ASSESSMENT = "invalid_assessment"


@dataclass(frozen=True, slots=True)
class ModerationRequest:
    """Normalized moderation input derived only from the durable event model."""

    event_id: str
    platform: Platform
    text: str | None
    media: dict[str, Any] | None

    @property
    def has_text(self) -> bool:
        return bool(self.text and self.text.strip())

    @property
    def has_media(self) -> bool:
        if not self.media:
            return False
        kind = self.media.get("kind")
        return not (isinstance(kind, str) and kind.strip().lower() == "none")


@dataclass(frozen=True, slots=True)
class ModerationAssessment:
    """Normalized, provider-neutral evidence returned by a moderation adapter."""

    verdict: ModerationVerdict
    severity: ModerationSeverity
    confidence: float
    categories: tuple[ModerationCategory, ...] = ()
    text_assessed: bool = False
    media_assessed: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("moderation confidence must be between 0 and 1")
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("moderation categories must not contain duplicates")


@dataclass(frozen=True, slots=True)
class ModerationDecision:
    """Deterministic policy result before persistence."""

    disposition: ModerationDisposition
    reasons: tuple[ModerationReason, ...]

    def __post_init__(self) -> None:
        if not self.reasons:
            raise ValueError("moderation decision must contain at least one reason")
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("moderation reasons must not contain duplicates")


@dataclass(frozen=True, slots=True)
class ModerationResult:
    """Persisted moderation result associated with one durable inbound event."""

    id: str
    event_id: str
    disposition: ModerationDisposition
    reasons: tuple[ModerationReason, ...]
    categories: tuple[ModerationCategory, ...]
    adapter_name: str
    adapter_version: str
    confidence: float | None
    created_at: datetime
