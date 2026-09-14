"""Domain contracts for exact-source, idempotent origin publishing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.events import OutboundAction, Platform


class PublicationSourceKind(StrEnum):
    """Authoritative durable source that supplied reply text."""

    FAQ = "faq"
    SUPERVISOR = "supervisor"
    FATWA = "fatwa"


class PublicationStatus(StrEnum):
    """Allowed outbound action lifecycle for V1 publishing."""

    PENDING = "pending"
    DISPATCHING = "dispatching"
    SUCCEEDED = "succeeded"
    UNCERTAIN = "uncertain"


class FatwaPublicationPolicy(StrEnum):
    """Configured post-fatwa destination policy."""

    TELEGRAM_ONLY = "telegram_only"
    ORIGIN_ONLY = "origin_only"
    BOTH = "both"

    @property
    def allows_origin_reply(self) -> bool:
        return self in {self.ORIGIN_ONLY, self.BOTH}


@dataclass(frozen=True, slots=True)
class PublishableContent:
    """Exact text plus immutable evidence identity selected for publication."""

    event_id: str
    platform: Platform
    target_id: str
    source_kind: PublicationSourceKind
    evidence_id: str
    text: str


@dataclass(frozen=True, slots=True)
class PublicationResult:
    """Durable action returned by the dispatcher and whether a provider was called."""

    action: OutboundAction
    provider_called: bool
