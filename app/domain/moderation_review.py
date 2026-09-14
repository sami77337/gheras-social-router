"""Durable human-review evidence for fail-closed moderation overrides."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ModerationHumanReviewStatus(StrEnum):
    """Lifecycle of one required human moderation review."""

    PENDING = "pending"
    RESOLVED = "resolved"


class ModerationHumanDecision(StrEnum):
    """Human decision after a machine moderation HUMAN_REVIEW outcome."""

    ALLOW_ROUTING = "allow_routing"
    BLOCK_ROUTING = "block_routing"


@dataclass(frozen=True, slots=True)
class ModerationHumanReview:
    """Persisted human-review request and optional resolution evidence."""

    id: str
    event_id: str
    moderation_result_id: str
    status: ModerationHumanReviewStatus
    decision: ModerationHumanDecision | None
    reviewer_ref: str | None
    external_review_key: str | None
    created_at: datetime
    resolved_at: datetime | None

    def __post_init__(self) -> None:
        if self.status is ModerationHumanReviewStatus.PENDING:
            if any(
                value is not None
                for value in (
                    self.decision,
                    self.reviewer_ref,
                    self.external_review_key,
                    self.resolved_at,
                )
            ):
                raise ValueError("pending moderation review cannot carry resolution evidence")
            return

        if (
            self.decision is None
            or self.reviewer_ref is None
            or self.external_review_key is None
            or self.resolved_at is None
        ):
            raise ValueError("resolved moderation review requires complete human evidence")
