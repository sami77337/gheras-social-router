"""Side-effect-free end-to-end replay composition for Gheras V1."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.domain.classification import (
    ClassificationAssessment,
    ClassificationRequest,
    ClassificationRoute,
)
from app.domain.events import NormalizedInboundEvent, Platform
from app.domain.faq import FAQResolutionStatus
from app.domain.fatwa import FatwaResultOutcome
from app.domain.moderation import (
    ModerationAssessment,
    ModerationDisposition,
    ModerationRequest,
)
from app.domain.publishing import (
    FatwaPublicationPolicy,
    PublicationSourceKind,
    PublicationStatus,
)
from app.domain.shadow import ShadowOutcome
from app.ingress.common import ExactIngestionCollector
from app.persistence.classification_repository import ClassificationRepository
from app.persistence.faq_repository import FAQRepository
from app.persistence.fatwa_repository import FatwaRepository
from app.persistence.moderation_repository import ModerationRepository
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
from app.services.publishing import PublishingNotEligible, PublishingService
from app.services.shadow import ShadowService
from app.services.supervisor import SupervisorService


class ReplayEvidenceConflict(RuntimeError):
    """Raised when replay evidence disagrees with already durable semantics."""


class ReplayInvariantError(RuntimeError):
    """Raised when composed V1 boundaries disagree during offline replay."""


@dataclass(frozen=True, slots=True)
class ReplayFAQApproval:
    faq_key: str
    answer_text: str
    source_ref: str
    approved_by: str
    approved_at: datetime


@dataclass(frozen=True, slots=True)
class ReplaySupervisorEvidence:
    transport_name: str
    external_thread_id: str
    external_response_key: str
    supervisor_ref: str
    text: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class ReplayFatwaEvidence:
    bridge_name: str
    external_case_id: str
    external_result_key: str
    outcome: FatwaResultOutcome
    answer_text: str | None
    approved_by: str | None
    source_ref: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class ReplayScenario:
    event: NormalizedInboundEvent
    moderation: ModerationAssessment
    classification: ClassificationAssessment | None = None
    faq_approval: ReplayFAQApproval | None = None
    supervisor: ReplaySupervisorEvidence | None = None
    fatwa: ReplayFatwaEvidence | None = None


@dataclass(frozen=True, slots=True)
class RecordedPublishCall:
    platform: Platform
    target_id: str
    text_sha256: str
    text_length: int


@dataclass(frozen=True, slots=True)
class ReplayResult:
    platform: Platform
    created_event: bool
    moderation_disposition: ModerationDisposition
    route: ClassificationRoute | None
    shadow_outcome: ShadowOutcome
    source_kind: PublicationSourceKind | None
    publication_status: PublicationStatus | None
    provider_called: bool


@dataclass(frozen=True, slots=True)
class ReplayReport:
    results: tuple[ReplayResult, ...]
    provider_call_count: int
    by_platform: dict[str, int]
    by_route: dict[str, int]
    by_shadow_outcome: dict[str, int]

    @classmethod
    def build(
        cls,
        results: tuple[ReplayResult, ...],
        *,
        provider_call_count: int,
    ) -> ReplayReport:
        return cls(
            results=results,
            provider_call_count=provider_call_count,
            by_platform=dict(Counter(result.platform.value for result in results)),
            by_route=dict(
                Counter(
                    result.route.value if result.route is not None else "none"
                    for result in results
                )
            ),
            by_shadow_outcome=dict(
                Counter(result.shadow_outcome.value for result in results)
            ),
        )


class _StaticModerationAdapter:
    name = "sandbox-replay-moderation"
    version = "1"

    def __init__(self, assessment: ModerationAssessment) -> None:
        self._assessment = assessment

    async def assess(self, request: ModerationRequest) -> ModerationAssessment:
        return self._assessment


class _StaticClassificationAdapter:
    name = "sandbox-replay-classification"
    version = "1"

    def __init__(self, assessment: ClassificationAssessment) -> None:
        self._assessment = assessment

    async def classify(self, request: ClassificationRequest) -> ClassificationAssessment:
        return self._assessment


class _RecordingPublisher:
    """Record content fingerprints only; never retain replay text."""

    def __init__(self, platform: Platform) -> None:
        self.platform = platform
        self.calls: list[RecordedPublishCall] = []

    async def publish_reply(self, *, external_comment_id: str, text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.calls.append(
            RecordedPublishCall(
                platform=self.platform,
                target_id=external_comment_id,
                text_sha256=digest,
                text_length=len(text),
            )
        )
        identity = hashlib.sha256(
            f"{self.platform.value}\0{external_comment_id}".encode()
        ).hexdigest()[:24]
        return f"sandbox-{identity}"


class SandboxReplayRuntime:
    """Compose V1 services over SQLite without any external transport or network call."""

    def __init__(
        self,
        database_path: Path,
        *,
        fatwa_policy: FatwaPublicationPolicy = FatwaPublicationPolicy.TELEGRAM_ONLY,
        evaluator_version: str = "sandbox-replay-v1",
    ) -> None:
        self.database = SQLiteDatabase(database_path)
        self.database.initialize()
        self.events = DurableRepository(self.database)
        self.moderation = ModerationRepository(self.database)
        self.classifications = ClassificationRepository(self.database)
        self.faqs = FAQRepository(self.database)
        self.supervisors = SupervisorRepository(self.database)
        self.fatwas = FatwaRepository(self.database)
        self.publications = PublishingRepository(self.database)
        self.shadows = ShadowRepository(self.database)
        self.moderation_policy = ModerationPolicy(minimum_confidence=0.80)
        self.classification_policy = ClassificationPolicy(minimum_faq_confidence=0.80)
        self.fatwa_policy = fatwa_policy
        self.evaluator_version = evaluator_version
        self._publishers = {platform: _RecordingPublisher(platform) for platform in Platform}

    @property
    def recorded_calls(self) -> tuple[RecordedPublishCall, ...]:
        return tuple(
            call for platform in Platform for call in self._publishers[platform].calls
        )

    async def replay(self, scenarios: Iterable[ReplayScenario]) -> ReplayReport:
        before = len(self.recorded_calls)
        results = tuple([await self.replay_one(scenario) for scenario in scenarios])
        return ReplayReport.build(
            results,
            provider_call_count=len(self.recorded_calls) - before,
        )

    async def replay_one(self, scenario: ReplayScenario) -> ReplayResult:
        ingestion = ExactIngestionCollector(IngestionService(self.events)).ingest(scenario.event)
        event = ingestion.event

        moderation_request = ModerationRequest(
            event_id=event.id,
            platform=event.platform,
            text=event.text,
            media=event.media,
        )
        expected_moderation = self.moderation_policy.decide(
            moderation_request,
            scenario.moderation,
        )
        moderation_result = await ModerationService(
            events=self.events,
            results=self.moderation,
            adapter=_StaticModerationAdapter(scenario.moderation),
            policy=self.moderation_policy,
        ).moderate(event.id)
        if (
            moderation_result.disposition is not expected_moderation.disposition
            or moderation_result.reasons != expected_moderation.reasons
            or moderation_result.categories != scenario.moderation.categories
            or moderation_result.confidence != scenario.moderation.confidence
        ):
            raise ReplayEvidenceConflict("durable moderation evidence differs from replay")

        route: ClassificationRoute | None = None
        if moderation_result.disposition is ModerationDisposition.ALLOW_ROUTING:
            if scenario.classification is None:
                raise ReplayInvariantError(
                    "allow_routing replay requires classification evidence"
                )
            classification_request = ClassificationRequest(
                event_id=event.id,
                platform=event.platform,
                text=event.text,
                media=event.media,
            )
            expected_classification = self.classification_policy.decide(
                classification_request,
                scenario.classification,
            )
            classification_result = await ClassificationService(
                events=self.events,
                moderation=self.moderation,
                results=self.classifications,
                adapter=_StaticClassificationAdapter(scenario.classification),
                policy=self.classification_policy,
            ).classify(event.id)
            if (
                classification_result.route is not expected_classification.route
                or classification_result.reasons != expected_classification.reasons
                or classification_result.faq_key != expected_classification.faq_key
                or classification_result.religious_possible
                is not scenario.classification.religious_possible
                or classification_result.confidence != scenario.classification.confidence
            ):
                raise ReplayEvidenceConflict(
                    "durable classification evidence differs from replay"
                )
            route = classification_result.route
            self._apply_route_evidence(event.id, route, scenario)
        elif scenario.faq_approval or scenario.supervisor or scenario.fatwa:
            raise ReplayEvidenceConflict(
                "blocked or human-review moderation cannot accept downstream route evidence"
            )

        shadow = ShadowService(
            events=self.events,
            moderation=self.moderation,
            classifications=self.classifications,
            faqs=self.faqs,
            supervisors=self.supervisors,
            fatwas=self.fatwas,
            shadows=self.shadows,
            evaluator_version=self.evaluator_version,
            fatwa_policy=self.fatwa_policy,
        ).evaluate(event.id)

        publication_status: PublicationStatus | None = None
        provider_called = False
        if shadow.outcome is ShadowOutcome.WOULD_PUBLISH:
            try:
                publication = await PublishingService(
                    events=self.events,
                    classifications=self.classifications,
                    faqs=self.faqs,
                    supervisors=self.supervisors,
                    fatwas=self.fatwas,
                    publications=self.publications,
                    publishers=self._publishers,
                    fatwa_policy=self.fatwa_policy,
                ).dispatch_origin(event.id)
            except PublishingNotEligible as exc:
                raise ReplayInvariantError(
                    "shadow would_publish disagrees with publishing eligibility"
                ) from exc
            publication_status = PublicationStatus(publication.action.status)
            provider_called = publication.provider_called

        return ReplayResult(
            platform=event.platform,
            created_event=ingestion.created,
            moderation_disposition=moderation_result.disposition,
            route=route,
            shadow_outcome=shadow.outcome,
            source_kind=shadow.source_kind,
            publication_status=publication_status,
            provider_called=provider_called,
        )

    def _apply_route_evidence(
        self,
        event_id: str,
        route: ClassificationRoute,
        scenario: ReplayScenario,
    ) -> None:
        if route is ClassificationRoute.FAQ:
            if scenario.fatwa is not None:
                raise ReplayEvidenceConflict("FAQ route cannot accept FATWA evidence")
            if scenario.faq_approval is not None:
                self._seed_faq(scenario.faq_approval)
            resolution = FAQService(
                classifications=self.classifications,
                faqs=self.faqs,
            ).resolve(event_id)
            if scenario.supervisor is not None:
                if resolution.resolution.status is not FAQResolutionStatus.SUPERVISOR_REQUIRED:
                    raise ReplayEvidenceConflict(
                        "resolved FAQ cannot also accept supervisor response evidence"
                    )
                self._apply_supervisor(event_id, scenario.supervisor)
            return

        if route is ClassificationRoute.SUPERVISOR:
            if scenario.faq_approval is not None or scenario.fatwa is not None:
                raise ReplayEvidenceConflict(
                    "SUPERVISOR route cannot accept FAQ or FATWA evidence"
                )
            if scenario.supervisor is not None:
                self._apply_supervisor(event_id, scenario.supervisor)
            return

        if scenario.faq_approval is not None or scenario.supervisor is not None:
            raise ReplayEvidenceConflict("FATWA route cannot accept FAQ or supervisor evidence")
        service = FatwaService(
            events=self.events,
            classifications=self.classifications,
            fatwas=self.fatwas,
        )
        service.ensure_request(event_id)
        if scenario.fatwa is not None:
            self._apply_fatwa(event_id, scenario.fatwa)

    def _seed_faq(self, approval: ReplayFAQApproval) -> None:
        active = self.faqs.get_active(approval.faq_key)
        if active is None:
            self.faqs.create_version(
                faq_key=approval.faq_key,
                answer_text=approval.answer_text,
                source_ref=approval.source_ref,
                approved_by=approval.approved_by,
                approved_at=approval.approved_at,
            )
            return
        if (
            active.answer_text != approval.answer_text
            or active.source_ref != approval.source_ref
            or active.approved_by != approval.approved_by
            or active.approved_at != approval.approved_at
        ):
            raise ReplayEvidenceConflict("active FAQ approval differs from replay evidence")

    def _apply_supervisor(
        self,
        event_id: str,
        evidence: ReplaySupervisorEvidence,
    ) -> None:
        service = SupervisorService(
            events=self.events,
            classifications=self.classifications,
            faqs=self.faqs,
            supervisors=self.supervisors,
        )
        service.mark_dispatched(
            event_id,
            transport_name=evidence.transport_name,
            external_thread_id=evidence.external_thread_id,
        )
        service.accept_response(
            event_id,
            external_response_key=evidence.external_response_key,
            supervisor_ref=evidence.supervisor_ref,
            text=evidence.text,
            received_at=evidence.received_at,
        )

    def _apply_fatwa(self, event_id: str, evidence: ReplayFatwaEvidence) -> None:
        service = FatwaService(
            events=self.events,
            classifications=self.classifications,
            fatwas=self.fatwas,
        )
        service.mark_dispatched(
            event_id,
            bridge_name=evidence.bridge_name,
            external_case_id=evidence.external_case_id,
        )
        service.accept_result(
            event_id,
            external_result_key=evidence.external_result_key,
            outcome=evidence.outcome,
            answer_text=evidence.answer_text,
            approved_by=evidence.approved_by,
            source_ref=evidence.source_ref,
            received_at=evidence.received_at,
        )
