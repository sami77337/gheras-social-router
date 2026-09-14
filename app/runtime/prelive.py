"""Explicit pre-live sandbox composition with no automatic external action."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from app.adapters.contracts import ReplyPublisher
from app.adapters.models.contracts import StructuredDecisionClient
from app.adapters.models.structured import (
    StructuredClassificationAdapter,
    StructuredModerationAdapter,
)
from app.api.integrations import IngressRuntime
from app.domain.classification import ClassificationRoute
from app.domain.events import Platform
from app.domain.faq import FAQResolutionStatus
from app.domain.moderation import ModerationDisposition
from app.domain.moderation_review import (
    ModerationHumanDecision,
    ModerationHumanReviewStatus,
)
from app.domain.publishing import FatwaPublicationPolicy
from app.domain.shadow import ShadowOutcome
from app.ingress.common import ExactIngestionCollector
from app.ingress.meta import MetaWebhookIngress
from app.ingress.telegram import TelegramWebhookIngress
from app.integrations.live.activation import (
    SandboxExecutionPermit,
    require_sandbox_execution,
)
from app.persistence.classification_repository import ClassificationRepository
from app.persistence.faq_repository import FAQRepository
from app.persistence.fatwa_repository import FatwaRepository
from app.persistence.moderation_repository import ModerationRepository
from app.persistence.moderation_review_repository import ModerationReviewRepository
from app.persistence.publishing_repository import PublishingRepository
from app.persistence.repositories import DurableRepository
from app.persistence.shadow_repository import ShadowRepository
from app.persistence.sqlite import SQLiteDatabase
from app.persistence.supervisor_repository import SupervisorRepository
from app.services.classification import ClassificationService
from app.services.classification_policy import ClassificationPolicy
from app.services.faq import FAQService
from app.services.fatwa import FatwaService
from app.services.ingestion import IngestionService
from app.services.moderation import ModerationService
from app.services.moderation_policy import ModerationPolicy
from app.services.moderation_review import ModerationReviewService
from app.services.publishing import PublishingService
from app.services.shadow import ShadowService
from app.services.supervisor import SupervisorService


@dataclass(frozen=True, slots=True)
class PreLiveProcessResult:
    """Content-free routing result from one explicit pre-live processing pass."""

    event_id: str
    moderation_disposition: ModerationDisposition
    route: ClassificationRoute | None
    shadow_outcome: ShadowOutcome


@dataclass(slots=True, repr=False)
class PreLiveSandboxRuntime:
    """Composed V1 boundaries; external actions remain explicit caller operations."""

    database: SQLiteDatabase
    events: DurableRepository
    moderation_results: ModerationRepository
    moderation_review_results: ModerationReviewRepository
    classification_results: ClassificationRepository
    faqs: FAQRepository
    supervisors: SupervisorRepository
    fatwas: FatwaRepository
    publications: PublishingRepository
    shadows: ShadowRepository
    ingestion: IngestionService
    moderation: ModerationService
    moderation_review: ModerationReviewService
    classification: ClassificationService
    faq: FAQService
    supervisor: SupervisorService
    fatwa: FatwaService
    shadow: ShadowService
    publishing: PublishingService
    ingress: IngressRuntime

    def __repr__(self) -> str:
        return "PreLiveSandboxRuntime(mode='sandbox', configured=True)"

    async def process_event(self, event_id: str) -> PreLiveProcessResult:
        """Advance durable routing state without dispatching any external action."""

        moderation = await self.moderation.moderate(event_id)
        if moderation.disposition is ModerationDisposition.BLOCK_ROUTING:
            shadow = self.shadow.evaluate(event_id)
            return PreLiveProcessResult(
                event_id=event_id,
                moderation_disposition=moderation.disposition,
                route=None,
                shadow_outcome=shadow.outcome,
            )

        if moderation.disposition is ModerationDisposition.HUMAN_REVIEW:
            review = self.moderation_review.ensure_review(event_id)
            if review.status is ModerationHumanReviewStatus.PENDING:
                return PreLiveProcessResult(
                    event_id=event_id,
                    moderation_disposition=moderation.disposition,
                    route=None,
                    shadow_outcome=ShadowOutcome.WOULD_WAIT_HUMAN,
                )
            if review.decision is ModerationHumanDecision.BLOCK_ROUTING:
                shadow = self.shadow.evaluate(event_id)
                return PreLiveProcessResult(
                    event_id=event_id,
                    moderation_disposition=moderation.disposition,
                    route=None,
                    shadow_outcome=shadow.outcome,
                )
            if review.decision is not ModerationHumanDecision.ALLOW_ROUTING:
                raise RuntimeError("resolved moderation review has invalid decision")

        classification = await self.classification.classify(event_id)
        if classification.route is ClassificationRoute.FAQ:
            resolution = self.faq.resolve(event_id)
            if resolution.resolution.status is FAQResolutionStatus.SUPERVISOR_REQUIRED:
                self.supervisor.ensure_escalation(event_id)
        elif classification.route is ClassificationRoute.SUPERVISOR:
            self.supervisor.ensure_escalation(event_id)
        elif classification.route is ClassificationRoute.FATWA:
            self.fatwa.ensure_request(event_id)

        shadow = self.shadow.evaluate(event_id)
        return PreLiveProcessResult(
            event_id=event_id,
            moderation_disposition=moderation.disposition,
            route=classification.route,
            shadow_outcome=shadow.outcome,
        )


def create_prelive_sandbox_runtime(
    database_path: Path,
    *,
    permit: SandboxExecutionPermit | None,
    moderation_client: StructuredDecisionClient,
    classification_client: StructuredDecisionClient,
    meta_app_secret: str,
    meta_verify_token: str,
    telegram_webhook_secret: str,
    publishers: Mapping[Platform, ReplyPublisher] | None = None,
    fatwa_policy: FatwaPublicationPolicy = FatwaPublicationPolicy.TELEGRAM_ONLY,
    evaluator_version: str = "prelive-sandbox-v1",
) -> PreLiveSandboxRuntime:
    """Create the pre-live graph only after explicit sandbox capability issuance."""

    require_sandbox_execution(permit)
    database = SQLiteDatabase(database_path)
    database.initialize()
    events = DurableRepository(database)
    moderation_results = ModerationRepository(database)
    moderation_review_results = ModerationReviewRepository(database)
    classification_results = ClassificationRepository(database)
    faqs = FAQRepository(database)
    supervisors = SupervisorRepository(database)
    fatwas = FatwaRepository(database)
    publications = PublishingRepository(database)
    shadows = ShadowRepository(database)
    ingestion = IngestionService(events)
    collector = ExactIngestionCollector(ingestion)

    moderation = ModerationService(
        events=events,
        results=moderation_results,
        adapter=StructuredModerationAdapter(moderation_client),
        policy=ModerationPolicy(minimum_confidence=0.80),
    )
    moderation_review = ModerationReviewService(
        moderation=moderation_results,
        reviews=moderation_review_results,
    )
    classification = ClassificationService(
        events=events,
        moderation=moderation_results,
        results=classification_results,
        adapter=StructuredClassificationAdapter(classification_client),
        policy=ClassificationPolicy(minimum_faq_confidence=0.80),
        moderation_reviews=moderation_review_results,
    )
    faq = FAQService(classifications=classification_results, faqs=faqs)
    supervisor = SupervisorService(
        events=events,
        classifications=classification_results,
        faqs=faqs,
        supervisors=supervisors,
    )
    fatwa = FatwaService(
        events=events,
        classifications=classification_results,
        fatwas=fatwas,
    )
    shadow = ShadowService(
        events=events,
        moderation=moderation_results,
        classifications=classification_results,
        faqs=faqs,
        supervisors=supervisors,
        fatwas=fatwas,
        shadows=shadows,
        evaluator_version=evaluator_version,
        fatwa_policy=fatwa_policy,
        moderation_reviews=moderation_review_results,
    )
    publishing = PublishingService(
        events=events,
        classifications=classification_results,
        faqs=faqs,
        supervisors=supervisors,
        fatwas=fatwas,
        publications=publications,
        publishers=dict(publishers or {}),
        fatwa_policy=fatwa_policy,
        moderation=moderation_results,
        moderation_reviews=moderation_review_results,
    )
    ingress = IngressRuntime(
        meta=MetaWebhookIngress(collector=collector, app_secret=meta_app_secret),
        telegram=TelegramWebhookIngress(
            collector=collector,
            webhook_secret=telegram_webhook_secret,
        ),
        meta_verify_token=meta_verify_token,
    )

    return PreLiveSandboxRuntime(
        database=database,
        events=events,
        moderation_results=moderation_results,
        moderation_review_results=moderation_review_results,
        classification_results=classification_results,
        faqs=faqs,
        supervisors=supervisors,
        fatwas=fatwas,
        publications=publications,
        shadows=shadows,
        ingestion=ingestion,
        moderation=moderation,
        moderation_review=moderation_review,
        classification=classification,
        faq=faq,
        supervisor=supervisor,
        fatwa=fatwa,
        shadow=shadow,
        publishing=publishing,
        ingress=ingress,
    )
