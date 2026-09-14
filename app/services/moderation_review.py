"""Application service for durable human moderation review and resume."""

from __future__ import annotations

from app.domain.moderation import ModerationDisposition
from app.domain.moderation_review import ModerationHumanDecision, ModerationHumanReview
from app.persistence.moderation_repository import ModerationRepository
from app.persistence.moderation_review_repository import ModerationReviewRepository


class ModerationReviewNotEligible(RuntimeError):
    """Raised when an event does not require human moderation review."""


class ModerationReviewService:
    """Create and resolve one human review without mutating machine evidence."""

    def __init__(
        self,
        *,
        moderation: ModerationRepository,
        reviews: ModerationReviewRepository,
    ) -> None:
        self.moderation = moderation
        self.reviews = reviews

    def ensure_review(self, event_id: str) -> ModerationHumanReview:
        result = self.moderation.get_for_event(event_id)
        if (
            result is None
            or result.disposition is not ModerationDisposition.HUMAN_REVIEW
        ):
            raise ModerationReviewNotEligible(
                "human review requires durable moderation disposition human_review"
            )
        return self.reviews.ensure_pending(
            event_id=event_id,
            moderation_result_id=result.id,
        )

    def resolve(
        self,
        event_id: str,
        *,
        decision: ModerationHumanDecision,
        reviewer_ref: str,
        external_review_key: str,
    ) -> ModerationHumanReview:
        self.ensure_review(event_id)
        return self.reviews.resolve(
            event_id=event_id,
            decision=decision,
            reviewer_ref=reviewer_ref,
            external_review_key=external_review_key,
        )
