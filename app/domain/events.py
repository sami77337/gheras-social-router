"""Typed domain models for normalized inbound events and durable actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.domain.states import ProcessingState


class Platform(StrEnum):
    """Platforms supported by Gheras Social Router V1."""

    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    TELEGRAM = "telegram"
    YOUTUBE = "youtube"


@dataclass(frozen=True, slots=True)
class NormalizedInboundEvent:
    """Platform-neutral event accepted from a future platform adapter."""

    platform: Platform
    external_event_key: str
    external_event_id: str | None = None
    external_comment_id: str | None = None
    external_post_id: str | None = None
    author_id: str | None = None
    text: str | None = None
    media: dict[str, Any] | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if not self.external_event_key.strip():
            raise ValueError("external_event_key must not be empty")


@dataclass(frozen=True, slots=True)
class InboundEvent:
    """Persisted normalized event."""

    id: str
    platform: Platform
    external_event_key: str
    external_event_id: str | None
    external_comment_id: str | None
    external_post_id: str | None
    author_id: str | None
    text: str | None
    media: dict[str, Any] | None
    correlation_id: str
    status: ProcessingState
    retry_count: int
    next_retry_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Result returned by idempotent persist-first ingestion."""

    event: InboundEvent
    created: bool


@dataclass(frozen=True, slots=True)
class ProcessingAttempt:
    """Sanitized record of one processing attempt."""

    id: str
    event_id: str
    attempt_number: int
    started_at: datetime
    finished_at: datetime | None
    outcome: str | None
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class OutboundAction:
    """Durable outbound publish intent/result protected by an idempotency key."""

    id: str
    event_id: str
    platform: Platform
    action_type: str
    idempotency_key: str
    status: str
    external_result_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class OutboundActionResult:
    """Result of idempotent outbound-action creation."""

    action: OutboundAction
    created: bool
