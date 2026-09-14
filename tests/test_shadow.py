from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.classification import (
    ClassificationDecision,
    ClassificationReason,
    ClassificationRoute,
)
from app.domain.events import NormalizedInboundEvent, Platform
from app.domain.fatwa import FatwaResultOutcome
from app.domain.moderation import (
    ModerationDecision,
    ModerationDisposition,
    ModerationReason,
)
from app.domain.publishing import FatwaPublicationPolicy, PublicationSourceKind
from app.domain.shadow import ShadowOutcome
from app.persistence.classification_repository import ClassificationRepository
from app.persistence.faq_repository import FAQRepository
from app.persistence.fatwa_repository import FatwaRepository
from app.persistence.moderation_repository import ModerationRepository
from app.persistence.repositories import DurableRepository
from app.persistence.shadow_repository import ShadowConflict, ShadowRepository
from app.persistence.sqlite import SQLiteDatabase
from app.persistence.supervisor_repository import SupervisorRepository
from app.services.faq import FAQService
from app.services.fatwa import FatwaService
from app.services.ingestion import IngestionService
from app.services.shadow import ShadowService
from app.services.supervisor import SupervisorService


class Fixture:
    def __init__(self, tmp_path: Path) -> None:
        self.database = SQLiteDatabase(tmp_path / "router.db")
        self.database.initialize()
        self.events = DurableRepository(self.database)
        self.moderation = ModerationRepository(self.database)
        self.classifications = ClassificationRepository(self.database)
        self.faqs = FAQRepository(self.database)
        self.supervisors = SupervisorRepository(self.database)
        self.fatwas = FatwaRepository(self.database)
        self.shadows = ShadowRepository(self.database)

    def ingest(
        self,
        *,
        key: str,
        platform: Platform = Platform.FACEBOOK,
        target: str | None = "comment-1",
    ) -> str:
        return IngestionService(self.events).ingest_event(
            NormalizedInboundEvent(
                platform=platform,
                external_event_key=key,
                external_comment_id=target,
                text="سؤال للاختبار",
            )
        ).event.id

    def moderate(self, event_id: str, disposition: ModerationDisposition) -> None:
        reason = {
            ModerationDisposition.ALLOW_ROUTING: ModerationReason.EXPLICIT_SAFE,
            ModerationDisposition.HUMAN_REVIEW: ModerationReason.UNCERTAIN_VERDICT,
            ModerationDisposition.BLOCK_ROUTING: ModerationReason.EXPLICIT_UNSAFE,
        }[disposition]
        self.moderation.create_for_event(
            event_id=event_id,
            decision=ModerationDecision(disposition=disposition, reasons=(reason,)),
            categories=(),
            adapter_name="test-moderation",
            adapter_version="1",
            confidence=1.0,
        )

    def classify(
        self,
        event_id: str,
        route: ClassificationRoute,
        *,
        faq_key: str | None = None,
    ) -> None:
        if route is ClassificationRoute.FAQ:
            decision = ClassificationDecision(
                route=route,
                reasons=(ClassificationReason.CONFIDENT_FAQ,),
                faq_key=faq_key or "fixture.key",
            )
            religious = False
        elif route is ClassificationRoute.SUPERVISOR:
            decision = ClassificationDecision(
                route=route,
                reasons=(ClassificationReason.EXPLICIT_SUPERVISOR,),
            )
            religious = False
        else:
            decision = ClassificationDecision(
                route=route,
                reasons=(ClassificationReason.RELIGIOUS_SAFETY_OVERRIDE,),
            )
            religious = True
        self.classifications.create_for_event(
            event_id=event_id,
            decision=decision,
            religious_possible=religious,
            confidence=0.99,
            adapter_name="test-classifier",
            adapter_version="1",
        )

    def service(
        self,
        *,
        evaluator_version: str = "shadow-v1",
        fatwa_policy: FatwaPublicationPolicy = FatwaPublicationPolicy.TELEGRAM_ONLY,
    ) -> ShadowService:
        return ShadowService(
            events=self.events,
            moderation=self.moderation,
            classifications=self.classifications,
            faqs=self.faqs,
            supervisors=self.supervisors,
            fatwas=self.fatwas,
            shadows=self.shadows,
            evaluator_version=evaluator_version,
            fatwa_policy=fatwa_policy,
        )

    def outbound_count(self) -> int:
        with self.database.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM outbound_actions").fetchone()
        return int(row["count"]) if row is not None else 0


def _prepare_faq(
    fx: Fixture,
    event_id: str,
    answer: str = "الجواب التشغيلي المعتمد كما هو",
) -> str:
    fx.classify(event_id, ClassificationRoute.FAQ, faq_key="registration.status")
    entry = fx.faqs.create_version(
        faq_key="registration.status",
        answer_text=answer,
        source_ref="fixture://faq/registration",
        approved_by="reviewer-1",
        approved_at=datetime(2026, 9, 10, 8, 0, tzinfo=UTC),
    )
    FAQService(classifications=fx.classifications, faqs=fx.faqs).resolve(event_id)
    return entry.id


def _supervisor_service(fx: Fixture) -> SupervisorService:
    return SupervisorService(
        events=fx.events,
        classifications=fx.classifications,
        faqs=fx.faqs,
        supervisors=fx.supervisors,
    )


def _prepare_supervisor_response(
    fx: Fixture,
    event_id: str,
    answer: str = "رد المشرف المعتمد حرفيًا",
) -> None:
    fx.classify(event_id, ClassificationRoute.SUPERVISOR)
    service = _supervisor_service(fx)
    service.mark_dispatched(
        event_id,
        transport_name="telegram",
        external_thread_id=f"thread-{event_id}",
    )
    service.accept_response(
        event_id,
        external_response_key=f"response-{event_id}",
        supervisor_ref="supervisor-1",
        text=answer,
        received_at=datetime(2026, 9, 10, 8, 5, tzinfo=UTC),
    )


def _prepare_fatwa_request(fx: Fixture, event_id: str) -> FatwaService:
    fx.classify(event_id, ClassificationRoute.FATWA)
    service = FatwaService(
        events=fx.events,
        classifications=fx.classifications,
        fatwas=fx.fatwas,
    )
    service.mark_dispatched(
        event_id,
        bridge_name="supervised-fatwa-system",
        external_case_id=f"case-{event_id}",
    )
    return service


def _approve_fatwa(
    fx: Fixture,
    event_id: str,
    answer: str = "جواب شرعي معتمد من الجهة الخارجية",
) -> None:
    service = _prepare_fatwa_request(fx, event_id)
    service.accept_result(
        event_id,
        external_result_key=f"result-{event_id}",
        outcome=FatwaResultOutcome.APPROVED,
        answer_text=answer,
        approved_by="scholar-reviewer-1",
        source_ref=f"fixture://fatwa/{event_id}",
        received_at=datetime(2026, 9, 10, 8, 10, tzinfo=UTC),
    )


def test_approved_faq_would_publish_exact_text_without_outbound_action(
    tmp_path: Path,
) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="faq-approved")
    fx.moderate(event_id, ModerationDisposition.ALLOW_ROUTING)
    answer = "النص المعتمد يبقى كما هو دون تعديل."
    _prepare_faq(fx, event_id, answer)
    before_state = fx.events.get_event(event_id).status

    evaluation = fx.service().evaluate(event_id)

    assert evaluation.outcome is ShadowOutcome.WOULD_PUBLISH
    assert evaluation.source_kind is PublicationSourceKind.FAQ
    assert evaluation.proposed_text == answer
    assert fx.outbound_count() == 0
    assert fx.events.get_event(event_id).status is before_state


def test_revoked_faq_is_blocked_without_publishable_text(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="faq-revoked")
    fx.moderate(event_id, ModerationDisposition.ALLOW_ROUTING)
    _prepare_faq(fx, event_id)
    fx.faqs.disable_active("registration.status")

    evaluation = fx.service().evaluate(event_id)

    assert evaluation.outcome is ShadowOutcome.BLOCKED
    assert evaluation.proposed_text is None
    assert evaluation.source_kind is None
    assert fx.outbound_count() == 0


def test_supervisor_pending_would_wait_human(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="supervisor-pending")
    fx.moderate(event_id, ModerationDisposition.ALLOW_ROUTING)
    fx.classify(event_id, ClassificationRoute.SUPERVISOR)
    _supervisor_service(fx).ensure_escalation(event_id)

    evaluation = fx.service().evaluate(event_id)

    assert evaluation.outcome is ShadowOutcome.WOULD_WAIT_HUMAN
    assert evaluation.observed_route is ClassificationRoute.SUPERVISOR
    assert evaluation.proposed_text is None
    assert fx.outbound_count() == 0


def test_supervisor_response_would_publish_exact_human_text(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="supervisor-responded")
    fx.moderate(event_id, ModerationDisposition.ALLOW_ROUTING)
    answer = "هذا نص بشري معتمد دون إعادة صياغة."
    _prepare_supervisor_response(fx, event_id, answer)

    evaluation = fx.service().evaluate(event_id)

    assert evaluation.outcome is ShadowOutcome.WOULD_PUBLISH
    assert evaluation.source_kind is PublicationSourceKind.SUPERVISOR
    assert evaluation.proposed_text == answer
    assert fx.outbound_count() == 0


def test_fatwa_awaiting_result_would_route_fatwa_without_text(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="fatwa-awaiting")
    fx.moderate(event_id, ModerationDisposition.ALLOW_ROUTING)
    _prepare_fatwa_request(fx, event_id)

    evaluation = fx.service().evaluate(event_id)

    assert evaluation.outcome is ShadowOutcome.WOULD_ROUTE_FATWA
    assert evaluation.observed_route is ClassificationRoute.FATWA
    assert evaluation.proposed_text is None
    assert fx.outbound_count() == 0


def test_approved_fatwa_default_policy_never_marks_origin_publishable(
    tmp_path: Path,
) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="fatwa-default")
    fx.moderate(event_id, ModerationDisposition.ALLOW_ROUTING)
    _approve_fatwa(fx, event_id)

    evaluation = fx.service().evaluate(event_id)

    assert evaluation.outcome is ShadowOutcome.WOULD_ROUTE_FATWA
    assert evaluation.proposed_text is None
    assert evaluation.source_kind is None
    assert fx.outbound_count() == 0


def test_explicit_origin_fatwa_policy_uses_exact_external_approved_text(
    tmp_path: Path,
) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="fatwa-origin")
    fx.moderate(event_id, ModerationDisposition.ALLOW_ROUTING)
    answer = "نص شرعي معتمد خارجيًا كما ورد حرفيًا."
    _approve_fatwa(fx, event_id, answer)

    evaluation = fx.service(
        fatwa_policy=FatwaPublicationPolicy.ORIGIN_ONLY
    ).evaluate(event_id)

    assert evaluation.outcome is ShadowOutcome.WOULD_PUBLISH
    assert evaluation.source_kind is PublicationSourceKind.FATWA
    assert evaluation.proposed_text == answer
    assert fx.outbound_count() == 0


def test_moderation_human_review_precedes_existing_classification(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="moderation-human")
    fx.moderate(event_id, ModerationDisposition.HUMAN_REVIEW)
    fx.classify(event_id, ClassificationRoute.FAQ, faq_key="ignored.key")

    evaluation = fx.service().evaluate(event_id)

    assert evaluation.outcome is ShadowOutcome.WOULD_WAIT_HUMAN
    assert evaluation.observed_route is None
    assert evaluation.proposed_text is None


def test_moderation_block_precedes_existing_classification(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="moderation-block")
    fx.moderate(event_id, ModerationDisposition.BLOCK_ROUTING)
    fx.classify(event_id, ClassificationRoute.FATWA)

    evaluation = fx.service().evaluate(event_id)

    assert evaluation.outcome is ShadowOutcome.BLOCKED
    assert evaluation.observed_route is None
    assert evaluation.proposed_text is None


def test_missing_moderation_is_not_ready_and_changes_no_event_state(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="not-ready")
    before = fx.events.get_event(event_id)

    evaluation = fx.service().evaluate(event_id)
    after = fx.events.get_event(event_id)

    assert evaluation.outcome is ShadowOutcome.NOT_READY
    assert after.status is before.status
    assert after.retry_count == before.retry_count
    assert after.next_retry_at == before.next_retry_at
    assert fx.outbound_count() == 0


@pytest.mark.parametrize("platform", list(Platform))
def test_shadow_supports_all_v1_platforms_without_external_action(
    tmp_path: Path,
    platform: Platform,
) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key=f"platform-{platform.value}", platform=platform)
    fx.moderate(event_id, ModerationDisposition.ALLOW_ROUTING)
    answer = f"رد معتمد {platform.value}"
    _prepare_supervisor_response(fx, event_id, answer)

    evaluation = fx.service().evaluate(event_id)

    assert evaluation.platform is platform
    assert evaluation.outcome is ShadowOutcome.WOULD_PUBLISH
    assert evaluation.proposed_text == answer
    assert fx.outbound_count() == 0


def test_duplicate_identical_evaluation_returns_same_durable_row(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="duplicate")
    fx.moderate(event_id, ModerationDisposition.ALLOW_ROUTING)
    _prepare_supervisor_response(fx, event_id)
    service = fx.service()

    first = service.evaluate(event_id)
    second = service.evaluate(event_id)

    assert first.id == second.id
    assert fx.shadows.count() == 1
    assert fx.outbound_count() == 0


def test_concurrent_identical_evaluations_converge_on_one_row(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="concurrent")
    fx.moderate(event_id, ModerationDisposition.ALLOW_ROUTING)
    _prepare_supervisor_response(fx, event_id)

    def evaluate() -> str:
        return fx.service().evaluate(event_id).id

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(lambda _: evaluate(), range(32)))

    assert len(set(ids)) == 1
    assert fx.shadows.count() == 1
    assert fx.outbound_count() == 0


def test_same_evaluator_version_conflicting_semantics_fail_closed(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="conflict")
    fx.moderate(event_id, ModerationDisposition.ALLOW_ROUTING)
    _prepare_faq(fx, event_id)
    service = fx.service(evaluator_version="shadow-conflict-v1")
    first = service.evaluate(event_id)
    assert first.outcome is ShadowOutcome.WOULD_PUBLISH

    fx.faqs.disable_active("registration.status")

    with pytest.raises(ShadowConflict):
        service.evaluate(event_id)
    assert fx.shadows.count() == 1
    assert fx.outbound_count() == 0


def test_shadow_evaluation_survives_database_restart(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="restart")
    fx.moderate(event_id, ModerationDisposition.ALLOW_ROUTING)
    _prepare_supervisor_response(fx, event_id)
    evaluation = fx.service().evaluate(event_id)

    restarted_database = SQLiteDatabase(tmp_path / "router.db")
    restarted_database.initialize()
    restarted_shadows = ShadowRepository(restarted_database)
    loaded = restarted_shadows.get(event_id, "shadow-v1")

    assert loaded is not None
    assert loaded.id == evaluation.id
    assert loaded.outcome is evaluation.outcome
    assert loaded.proposed_text == evaluation.proposed_text


def test_summary_exposes_counts_without_reply_content(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)

    faq_event = fx.ingest(key="summary-faq")
    fx.moderate(faq_event, ModerationDisposition.ALLOW_ROUTING)
    secretish_answer = "نص تقييم لا يجب أن يظهر في التقرير التجميعي"
    _prepare_faq(fx, faq_event, secretish_answer)
    fx.service(evaluator_version="summary-v1").evaluate(faq_event)

    blocked_event = fx.ingest(key="summary-blocked", platform=Platform.YOUTUBE)
    fx.moderate(blocked_event, ModerationDisposition.BLOCK_ROUTING)
    fx.service(evaluator_version="summary-v1").evaluate(blocked_event)

    summary = fx.shadows.summary()

    assert summary.total_evaluated == 2
    assert summary.publishable == 1
    assert summary.non_publishable == 1
    assert summary.by_outcome[ShadowOutcome.WOULD_PUBLISH.value] == 1
    assert summary.by_outcome[ShadowOutcome.BLOCKED.value] == 1
    assert summary.by_platform[Platform.FACEBOOK.value] == 1
    assert summary.by_platform[Platform.YOUTUBE.value] == 1
    assert secretish_answer not in repr(summary)
    assert fx.outbound_count() == 0
