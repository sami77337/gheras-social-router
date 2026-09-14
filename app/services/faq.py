"""Approved FAQ resolution after durable semantic classification."""

from __future__ import annotations

from app.domain.classification import ClassificationRoute
from app.domain.faq import (
    FAQResolutionReason,
    FAQResolutionResult,
    FAQResolutionStatus,
)
from app.persistence.classification_repository import ClassificationRepository
from app.persistence.faq_repository import FAQRepository


class FAQNotEligible(RuntimeError):
    """Raised when FAQ resolution is attempted for a non-FAQ classification."""


class FAQService:
    """Resolve exact FAQ keys against explicitly approved active entries only."""

    def __init__(
        self,
        *,
        classifications: ClassificationRepository,
        faqs: FAQRepository,
    ) -> None:
        self.classifications = classifications
        self.faqs = faqs

    def resolve(self, event_id: str) -> FAQResolutionResult:
        """Resolve one classified FAQ event without generation or fuzzy lookup."""

        classification = self.classifications.get_for_event(event_id)
        if classification is None or classification.route is not ClassificationRoute.FAQ:
            raise FAQNotEligible("FAQ resolution requires a durable FAQ classification")

        existing = self.faqs.get_resolution(event_id)
        if existing is not None:
            entry = (
                self.faqs.get_entry(existing.faq_entry_id)
                if existing.faq_entry_id is not None
                else None
            )
            return FAQResolutionResult(resolution=existing, entry=entry)

        faq_key = classification.faq_key
        if faq_key is None:
            resolution = self.faqs.create_resolution(
                event_id=event_id,
                classification_result_id=classification.id,
                status=FAQResolutionStatus.SUPERVISOR_REQUIRED,
                reason=FAQResolutionReason.INVALID_FAQ_KEY,
                faq_entry_id=None,
            )
            return FAQResolutionResult(resolution=resolution, entry=None)

        try:
            active = self.faqs.get_active(faq_key)
        except ValueError:
            resolution = self.faqs.create_resolution(
                event_id=event_id,
                classification_result_id=classification.id,
                status=FAQResolutionStatus.SUPERVISOR_REQUIRED,
                reason=FAQResolutionReason.INVALID_FAQ_KEY,
                faq_entry_id=None,
            )
            return FAQResolutionResult(resolution=resolution, entry=None)

        if active is None:
            try:
                historical_exists = self.faqs.has_versions(faq_key)
            except ValueError:
                historical_exists = False
            reason = (
                FAQResolutionReason.ENTRY_DISABLED
                if historical_exists
                else FAQResolutionReason.ENTRY_NOT_FOUND
            )
            resolution = self.faqs.create_resolution(
                event_id=event_id,
                classification_result_id=classification.id,
                status=FAQResolutionStatus.SUPERVISOR_REQUIRED,
                reason=reason,
                faq_entry_id=None,
            )
            return FAQResolutionResult(resolution=resolution, entry=None)

        try:
            resolution = self.faqs.create_resolution(
                event_id=event_id,
                classification_result_id=classification.id,
                status=FAQResolutionStatus.RESOLVED,
                reason=FAQResolutionReason.APPROVED_ENTRY,
                faq_entry_id=active.id,
            )
        except ValueError as exc:
            if "still be active" not in str(exc):
                raise
            resolution = self.faqs.create_resolution(
                event_id=event_id,
                classification_result_id=classification.id,
                status=FAQResolutionStatus.SUPERVISOR_REQUIRED,
                reason=FAQResolutionReason.ENTRY_DISABLED,
                faq_entry_id=None,
            )
            return FAQResolutionResult(resolution=resolution, entry=None)

        winner_entry = (
            self.faqs.get_entry(resolution.faq_entry_id)
            if resolution.faq_entry_id is not None
            else None
        )
        return FAQResolutionResult(resolution=resolution, entry=winner_entry)
