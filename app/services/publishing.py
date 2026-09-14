"""Exact-source publishing dispatcher with durable claim and uncertainty handling."""

from __future__ import annotations

from collections.abc import Mapping

from app.adapters.contracts import ReplyPublisher
from app.domain.classification import ClassificationRoute
from app.domain.events import Platform
from app.domain.faq import FAQEntryStatus, FAQResolutionStatus
from app.domain.fatwa import FatwaBridgeStatus
from app.domain.moderation import ModerationDisposition
from app.domain.moderation_review import (
    ModerationHumanDecision,
    ModerationHumanReviewStatus,
)
from app.domain.publishing import (
    FatwaPublicationPolicy,
    PublicationResult,
    PublicationSourceKind,
    PublicationStatus,
    PublishableContent,
)
from app.domain.supervisor import SupervisorEscalationStatus
from app.persistence.classification_repository import ClassificationRepository
from app.persistence.faq_repository import FAQRepository
from app.persistence.fatwa_repository import FatwaRepository
from app.persistence.moderation_repository import ModerationRepository
from app.persistence.moderation_review_repository import ModerationReviewRepository
from app.persistence.publishing_repository import PublishingRepository
from app.persistence.repositories import DurableRepository
from app.persistence.supervisor_repository import SupervisorRepository


class PublishingNotEligible(RuntimeError):
    """Raised when durable upstream evidence does not authorize publication."""


class PublisherUnavailable(RuntimeError):
    """Raised when no injected publisher exists for the event platform."""


class PublicationInFlight(RuntimeError):
    """Raised instead of calling a provider twice while another attempt is dispatching."""


class PublicationUncertain(RuntimeError):
    """Raised when an external call may have succeeded but durable confirmation is absent."""


class PublishingService:
    """Select exact approved text and dispatch it once through an injected publisher."""

    def __init__(
        self,
        *,
        events: DurableRepository,
        classifications: ClassificationRepository,
        faqs: FAQRepository,
        supervisors: SupervisorRepository,
        fatwas: FatwaRepository,
        publications: PublishingRepository,
        publishers: Mapping[Platform, ReplyPublisher],
        fatwa_policy: FatwaPublicationPolicy = FatwaPublicationPolicy.TELEGRAM_ONLY,
        moderation: ModerationRepository | None = None,
        moderation_reviews: ModerationReviewRepository | None = None,
    ) -> None:
        self.events = events
        self.classifications = classifications
        self.faqs = faqs
        self.supervisors = supervisors
        self.fatwas = fatwas
        self.publications = publications
        self.publishers = publishers
        self.fatwa_policy = fatwa_policy
        self.moderation = moderation
        self.moderation_reviews = moderation_reviews

    def _effective_moderation_allows(self, event_id: str) -> bool:
        if self.moderation is None:
            return True
        result = self.moderation.get_for_event(event_id)
        if result is None:
            return False
        if result.disposition is ModerationDisposition.ALLOW_ROUTING:
            return True
        if result.disposition is not ModerationDisposition.HUMAN_REVIEW:
            return False
        if self.moderation_reviews is None:
            return False
        review = self.moderation_reviews.get_for_event(event_id)
        return bool(
            review is not None
            and review.status is ModerationHumanReviewStatus.RESOLVED
            and review.decision is ModerationHumanDecision.ALLOW_ROUTING
        )

    def resolve_content(self, event_id: str) -> PublishableContent:
        """Resolve exact durable source text without generation or transformation."""

        event = self.events.get_event(event_id)
        if not self._effective_moderation_allows(event_id):
            raise PublishingNotEligible(
                "publication requires effective moderation allow_routing"
            )
        if event.external_comment_id is None or not event.external_comment_id.strip():
            raise PublishingNotEligible("origin event has no publishable reply target")
        classification = self.classifications.get_for_event(event_id)
        if classification is None:
            raise PublishingNotEligible("publication requires durable classification evidence")

        if classification.route is ClassificationRoute.FAQ:
            resolution = self.faqs.get_resolution(event_id)
            if resolution is None:
                raise PublishingNotEligible("FAQ route has no durable resolution")
            if resolution.status is FAQResolutionStatus.RESOLVED:
                if resolution.faq_entry_id is None:
                    raise PublishingNotEligible("resolved FAQ has no exact entry evidence")
                entry = self.faqs.get_entry(resolution.faq_entry_id)
                if entry.status is not FAQEntryStatus.ACTIVE:
                    raise PublishingNotEligible("resolved FAQ entry has been revoked")
                return PublishableContent(
                    event_id=event.id,
                    platform=event.platform,
                    target_id=event.external_comment_id,
                    source_kind=PublicationSourceKind.FAQ,
                    evidence_id=f"{resolution.id}.{entry.id}",
                    text=entry.answer_text,
                )
            return self._supervisor_content(event.id, event.platform, event.external_comment_id)

        if classification.route is ClassificationRoute.SUPERVISOR:
            return self._supervisor_content(event.id, event.platform, event.external_comment_id)

        if classification.route is ClassificationRoute.FATWA:
            if not self.fatwa_policy.allows_origin_reply:
                raise PublishingNotEligible(
                    "configured FATWA publication policy does not allow origin reply"
                )
            request = self.fatwas.get_for_event(event_id)
            if request is None or request.status is not FatwaBridgeStatus.APPROVED_RESULT:
                raise PublishingNotEligible("FATWA route has no approved external result")
            result = self.fatwas.get_result(request.id)
            if result is None or result.publishable_answer is None:
                raise PublishingNotEligible("FATWA result is not publishable")
            return PublishableContent(
                event_id=event.id,
                platform=event.platform,
                target_id=event.external_comment_id,
                source_kind=PublicationSourceKind.FATWA,
                evidence_id=result.id,
                text=result.publishable_answer,
            )

        raise PublishingNotEligible("unsupported classification route")

    def _supervisor_content(
        self,
        event_id: str,
        platform: Platform,
        target_id: str,
    ) -> PublishableContent:
        escalation = self.supervisors.get_for_event(event_id)
        if escalation is None or escalation.status is not SupervisorEscalationStatus.RESPONDED:
            raise PublishingNotEligible("supervisor route has no accepted human response")
        response = self.supervisors.get_response(escalation.id)
        if response is None:
            raise PublishingNotEligible("responded escalation is missing durable response")
        return PublishableContent(
            event_id=event_id,
            platform=platform,
            target_id=target_id,
            source_kind=PublicationSourceKind.SUPERVISOR,
            evidence_id=response.id,
            text=response.text,
        )

    async def dispatch_origin(self, event_id: str) -> PublicationResult:
        """Publish once or return/raise from durable state without blind retries."""

        content = self.resolve_content(event_id)
        publisher = self.publishers.get(content.platform)
        if publisher is None:
            raise PublisherUnavailable(f"no publisher configured for {content.platform.value}")

        action = self.publications.ensure_action(content)
        status = PublicationStatus(action.status)
        if status is PublicationStatus.SUCCEEDED:
            return PublicationResult(action=action, provider_called=False)
        if status is PublicationStatus.UNCERTAIN:
            raise PublicationUncertain("publication outcome requires reconciliation")
        if status is PublicationStatus.DISPATCHING:
            raise PublicationInFlight("publication is already being dispatched")

        claimed, acquired = self.publications.claim(action.id)
        if not acquired:
            current_status = PublicationStatus(claimed.status)
            if current_status is PublicationStatus.SUCCEEDED:
                return PublicationResult(action=claimed, provider_called=False)
            if current_status is PublicationStatus.UNCERTAIN:
                raise PublicationUncertain("publication outcome requires reconciliation")
            raise PublicationInFlight("publication is already being dispatched")

        try:
            external_result_id = await publisher.publish_reply(
                external_comment_id=content.target_id,
                text=content.text,
            )
            succeeded = self.publications.mark_succeeded(
                claimed.id,
                external_result_id,
            )
        except Exception:
            self.publications.mark_uncertain(claimed.id)
            raise PublicationUncertain(
                "provider attempt began but outcome could not be confirmed"
            ) from None

        return PublicationResult(action=succeeded, provider_called=True)
