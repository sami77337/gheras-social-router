"""Side-effect-free evaluation of durable Gheras routing and reply evidence."""

from __future__ import annotations

from app.domain.classification import ClassificationRoute
from app.domain.faq import FAQEntryStatus, FAQResolutionStatus
from app.domain.fatwa import FatwaBridgeStatus
from app.domain.moderation import ModerationDisposition
from app.domain.moderation_review import (
    ModerationHumanDecision,
    ModerationHumanReviewStatus,
)
from app.domain.publishing import FatwaPublicationPolicy, PublicationSourceKind
from app.domain.shadow import ShadowDecision, ShadowEvaluation, ShadowOutcome, ShadowSummary
from app.domain.supervisor import SupervisorEscalationStatus
from app.persistence.classification_repository import ClassificationRepository
from app.persistence.faq_repository import FAQRepository
from app.persistence.fatwa_repository import FatwaRepository
from app.persistence.moderation_repository import ModerationRepository
from app.persistence.moderation_review_repository import ModerationReviewRepository
from app.persistence.repositories import DurableRepository
from app.persistence.shadow_repository import ShadowRepository
from app.persistence.supervisor_repository import SupervisorRepository


class ShadowService:
    """Evaluate what durable evidence permits without invoking any external adapter."""

    def __init__(
        self,
        *,
        events: DurableRepository,
        moderation: ModerationRepository,
        classifications: ClassificationRepository,
        faqs: FAQRepository,
        supervisors: SupervisorRepository,
        fatwas: FatwaRepository,
        shadows: ShadowRepository,
        evaluator_version: str = "shadow-v1",
        fatwa_policy: FatwaPublicationPolicy = FatwaPublicationPolicy.TELEGRAM_ONLY,
        moderation_reviews: ModerationReviewRepository | None = None,
    ) -> None:
        self.events = events
        self.moderation = moderation
        self.classifications = classifications
        self.faqs = faqs
        self.supervisors = supervisors
        self.fatwas = fatwas
        self.shadows = shadows
        self.evaluator_version = evaluator_version
        self.fatwa_policy = fatwa_policy
        self.moderation_reviews = moderation_reviews

    def _human_review_outcome(self, event_id: str) -> ShadowOutcome | None:
        if self.moderation_reviews is None:
            return ShadowOutcome.WOULD_WAIT_HUMAN
        review = self.moderation_reviews.get_for_event(event_id)
        if review is None or review.status is ModerationHumanReviewStatus.PENDING:
            return ShadowOutcome.WOULD_WAIT_HUMAN
        if review.decision is ModerationHumanDecision.BLOCK_ROUTING:
            return ShadowOutcome.BLOCKED
        if review.decision is ModerationHumanDecision.ALLOW_ROUTING:
            return None
        return ShadowOutcome.BLOCKED

    def evaluate(self, event_id: str) -> ShadowEvaluation:
        """Compute and persist one immutable shadow observation for an event."""

        moderation = self.moderation.get_for_event(event_id)

        if moderation is None:
            return self._record(event_id, ShadowOutcome.NOT_READY)
        if moderation.disposition is ModerationDisposition.BLOCK_ROUTING:
            return self._record(event_id, ShadowOutcome.BLOCKED)
        if moderation.disposition is ModerationDisposition.HUMAN_REVIEW:
            review_outcome = self._human_review_outcome(event_id)
            if review_outcome is not None:
                return self._record(event_id, review_outcome)

        classification = self.classifications.get_for_event(event_id)
        if classification is None:
            return self._record(event_id, ShadowOutcome.NOT_READY)

        route = classification.route
        if route is ClassificationRoute.FAQ:
            return self._evaluate_faq(event_id, route)
        if route is ClassificationRoute.SUPERVISOR:
            return self._evaluate_supervisor(event_id, route)
        if route is ClassificationRoute.FATWA:
            return self._evaluate_fatwa(event_id, route)
        return self._record(event_id, ShadowOutcome.BLOCKED, route=route)

    def summary(self) -> ShadowSummary:
        """Return content-free aggregate metrics for all persisted shadow evaluations."""

        return self.shadows.summary()

    def _evaluate_faq(
        self,
        event_id: str,
        route: ClassificationRoute,
    ) -> ShadowEvaluation:
        resolution = self.faqs.get_resolution(event_id)
        if resolution is None:
            return self._record(event_id, ShadowOutcome.NOT_READY, route=route)

        if resolution.status is FAQResolutionStatus.RESOLVED:
            if resolution.faq_entry_id is None:
                return self._record(event_id, ShadowOutcome.BLOCKED, route=route)
            try:
                entry = self.faqs.get_entry(resolution.faq_entry_id)
            except LookupError:
                return self._record(event_id, ShadowOutcome.BLOCKED, route=route)
            if entry.status is not FAQEntryStatus.ACTIVE:
                return self._record(event_id, ShadowOutcome.BLOCKED, route=route)
            return self._record(
                event_id,
                ShadowOutcome.WOULD_PUBLISH,
                route=route,
                source_kind=PublicationSourceKind.FAQ,
                evidence_id=f"{resolution.id}.{entry.id}",
                proposed_text=entry.answer_text,
            )

        return self._evaluate_supervisor(event_id, route)

    def _evaluate_supervisor(
        self,
        event_id: str,
        route: ClassificationRoute,
    ) -> ShadowEvaluation:
        escalation = self.supervisors.get_for_event(event_id)
        if escalation is None:
            return self._record(event_id, ShadowOutcome.WOULD_WAIT_HUMAN, route=route)
        if escalation.status is SupervisorEscalationStatus.CANCELLED:
            return self._record(event_id, ShadowOutcome.BLOCKED, route=route)
        if escalation.status is not SupervisorEscalationStatus.RESPONDED:
            return self._record(event_id, ShadowOutcome.WOULD_WAIT_HUMAN, route=route)

        response = self.supervisors.get_response(escalation.id)
        if response is None:
            return self._record(event_id, ShadowOutcome.BLOCKED, route=route)
        return self._record(
            event_id,
            ShadowOutcome.WOULD_PUBLISH,
            route=route,
            source_kind=PublicationSourceKind.SUPERVISOR,
            evidence_id=response.id,
            proposed_text=response.text,
        )

    def _evaluate_fatwa(
        self,
        event_id: str,
        route: ClassificationRoute,
    ) -> ShadowEvaluation:
        request = self.fatwas.get_for_event(event_id)
        if request is None:
            return self._record(event_id, ShadowOutcome.WOULD_ROUTE_FATWA, route=route)
        if request.status in {
            FatwaBridgeStatus.PENDING_DISPATCH,
            FatwaBridgeStatus.AWAITING_RESULT,
        }:
            return self._record(event_id, ShadowOutcome.WOULD_ROUTE_FATWA, route=route)
        if request.status in {FatwaBridgeStatus.REJECTED, FatwaBridgeStatus.CANCELLED}:
            return self._record(event_id, ShadowOutcome.BLOCKED, route=route)
        if request.status is not FatwaBridgeStatus.APPROVED_RESULT:
            return self._record(event_id, ShadowOutcome.BLOCKED, route=route)

        result = self.fatwas.get_result(request.id)
        if result is None or result.publishable_answer is None:
            return self._record(event_id, ShadowOutcome.BLOCKED, route=route)
        if not self.fatwa_policy.allows_origin_reply:
            return self._record(event_id, ShadowOutcome.WOULD_ROUTE_FATWA, route=route)
        return self._record(
            event_id,
            ShadowOutcome.WOULD_PUBLISH,
            route=route,
            source_kind=PublicationSourceKind.FATWA,
            evidence_id=result.id,
            proposed_text=result.publishable_answer,
        )

    def _record(
        self,
        event_id: str,
        outcome: ShadowOutcome,
        *,
        route: ClassificationRoute | None = None,
        source_kind: PublicationSourceKind | None = None,
        evidence_id: str | None = None,
        proposed_text: str | None = None,
    ) -> ShadowEvaluation:
        event = self.events.get_event(event_id)
        decision = ShadowDecision(
            event_id=event.id,
            correlation_id=event.correlation_id,
            platform=event.platform,
            evaluator_version=self.evaluator_version,
            observed_route=route,
            outcome=outcome,
            source_kind=source_kind,
            evidence_id=evidence_id,
            proposed_text=proposed_text,
        )
        return self.shadows.record(decision)
