"""Approved FAQ domain models for traceable, non-generated operational answers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class FAQEntryStatus(StrEnum):
    """Lifecycle state for one immutable FAQ version row."""

    ACTIVE = "active"
    DISABLED = "disabled"


class FAQResolutionStatus(StrEnum):
    """Outcome of resolving an eligible FAQ classification."""

    RESOLVED = "resolved"
    SUPERVISOR_REQUIRED = "supervisor_required"


class FAQResolutionReason(StrEnum):
    """Machine-readable reason for a FAQ resolution outcome."""

    APPROVED_ENTRY = "approved_entry"
    ENTRY_NOT_FOUND = "entry_not_found"
    ENTRY_DISABLED = "entry_disabled"
    INVALID_FAQ_KEY = "invalid_faq_key"


@dataclass(frozen=True, slots=True)
class FAQEntry:
    """One immutable approved-answer version."""

    id: str
    faq_key: str
    version: int
    answer_text: str
    source_ref: str
    status: FAQEntryStatus
    approved_by: str
    approved_at: datetime
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FAQResolution:
    """Durable resolution linked to exact classification and FAQ evidence."""

    id: str
    event_id: str
    classification_result_id: str
    faq_entry_id: str | None
    status: FAQResolutionStatus
    reason: FAQResolutionReason
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FAQResolutionResult:
    """Resolution plus answer text only while the exact approved entry stays active."""

    resolution: FAQResolution
    entry: FAQEntry | None

    @property
    def answer_text(self) -> str | None:
        if self.resolution.status is not FAQResolutionStatus.RESOLVED:
            return None
        if self.entry is None:
            raise RuntimeError("resolved FAQ result is missing its approved entry")
        if self.entry.status is not FAQEntryStatus.ACTIVE:
            return None
        return self.entry.answer_text
