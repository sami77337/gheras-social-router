"""Domain models for the isolated supervised fatwa-system bridge."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class FatwaBridgeStatus(StrEnum):
    """Lifecycle for one durable FATWA bridge request."""

    PENDING_DISPATCH = "pending_dispatch"
    AWAITING_RESULT = "awaiting_result"
    APPROVED_RESULT = "approved_result"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class FatwaResultOutcome(StrEnum):
    """Normalized supervised-system result outcome."""

    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class FatwaBridgeRequest:
    """One durable request linked to an authoritative FATWA classification."""

    id: str
    event_id: str
    classification_result_id: str
    status: FatwaBridgeStatus
    dispatch_attempt_count: int
    bridge_name: str | None
    external_case_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class FatwaBridgeDispatch:
    """Minimal provider-neutral dispatch payload for the supervised fatwa system."""

    request_id: str
    event_id: str
    platform: str
    question_text: str | None
    correlation_id: str


@dataclass(frozen=True, slots=True)
class FatwaBridgeResult:
    """One accepted normalized result from the external supervised fatwa system."""

    id: str
    request_id: str
    external_result_key: str
    outcome: FatwaResultOutcome
    answer_text: str | None
    approved_by: str | None
    source_ref: str
    received_at: datetime

    @property
    def publishable_answer(self) -> str | None:
        """Return text only for an externally approved, fully attributed result."""

        if self.outcome is not FatwaResultOutcome.APPROVED:
            return None
        if self.answer_text is None or self.approved_by is None:
            raise RuntimeError("approved fatwa result is missing approval evidence")
        return self.answer_text
