from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.adapters.contracts import ReplyPublisher
from app.domain.classification import (
    ClassificationDecision,
    ClassificationReason,
    ClassificationRoute,
)
from app.domain.events import NormalizedInboundEvent, Platform
from app.domain.fatwa import FatwaResultOutcome
from app.domain.publishing import FatwaPublicationPolicy, PublicationStatus
from app.persistence.classification_repository import ClassificationRepository
from app.persistence.faq_repository import FAQRepository
from app.persistence.fatwa_repository import FatwaRepository
from app.persistence.publishing_repository import PublishingRepository
from app.persistence.repositories import DurableRepository
from app.persistence.sqlite import SQLiteDatabase
from app.persistence.supervisor_repository import SupervisorRepository
from app.services.faq import FAQService
from app.services.fatwa import FatwaService
from app.services.ingestion import IngestionService
from app.services.publishing import (
    PublicationInFlight,
    PublicationUncertain,
    PublishingNotEligible,
    PublishingService,
)
from app.services.supervisor import SupervisorService


class FakePublisher:
    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.fail = fail
        self.delay = delay
        self.calls: list[tuple[str, str]] = []

    async def publish_reply(self, *, external_comment_id: str, text: str) -> str:
        self.calls.append((external_comment_id, text))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("Bearer secret-that-must-not-drive-a-retry")
        return f"external-{external_comment_id}"


class Fixture:
    def __init__(self, tmp_path: Path) -> None:
        self.database = SQLiteDatabase(tmp_path / "router.db")
        self.database.initialize()
        self.events = DurableRepository(self.database)
        self.classifications = ClassificationRepository(self.database)
        self.faqs = FAQRepository(self.database)
        self.supervisors = SupervisorRepository(self.database)
        self.fatwas = FatwaRepository(self.database)
        self.publications = PublishingRepository(self.database)

    def ingest(
        self,
        *,
        key: str,
        platform: Platform = Platform.FACEBOOK,
        text: str = "سؤال",
        target: str | None = "comment-1",
    ) -> str:
        return IngestionService(self.events).ingest_event(
            NormalizedInboundEvent(
                platform=platform,
                external_event_key=key,
                external_comment_id=target,
                text=text,
            )
        ).event.id

    def classify(
        self,
        event_id: str,
        route: ClassificationRoute,
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
        publisher: ReplyPublisher,
        *,
        platform: Platform = Platform.FACEBOOK,
        fatwa_policy: FatwaPublicationPolicy = FatwaPublicationPolicy.TELEGRAM_ONLY,
    ) -> PublishingService:
        return PublishingService(
            events=self.events,
            classifications=self.classifications,
            faqs=self.faqs,
            supervisors=self.supervisors,
            fatwas=self.fatwas,
            publications=self.publications,
            publishers={platform: publisher},
            fatwa_policy=fatwa_policy,
        )


def _prepare_faq(fx: Fixture, event_id: str, answer: str = "الجواب المعتمد") -> str:
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


def _prepare_supervisor(fx: Fixture, event_id: str, answer: str = "رد المشرف") -> None:
    fx.classify(event_id, ClassificationRoute.SUPERVISOR)
    service = SupervisorService(
        events=fx.events,
        classifications=fx.classifications,
        faqs=fx.faqs,
        supervisors=fx.supervisors,
    )
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


def _prepare_fatwa(fx: Fixture, event_id: str, answer: str = "جواب شرعي معتمد") -> None:
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
    service.accept_result(
        event_id,
        external_result_key=f"result-{event_id}",
        outcome=FatwaResultOutcome.APPROVED,
        answer_text=answer,
        approved_by="scholar-reviewer-1",
        source_ref=f"fixture://fatwa/{event_id}",
        received_at=datetime(2026, 9, 10, 8, 10, tzinfo=UTC),
    )


def test_faq_publishes_exact_active_approved_text(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="faq", target="fb-comment-1")
    answer = "النص المعتمد كما هو، دون إعادة صياغة."
    _prepare_faq(fx, event_id, answer)
    publisher = FakePublisher()

    result = asyncio.run(fx.service(publisher).dispatch_origin(event_id))

    assert result.provider_called is True
    assert result.action.status == PublicationStatus.SUCCEEDED.value
    assert publisher.calls == [("fb-comment-1", answer)]


def test_revoked_faq_is_blocked_before_publisher_call(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="faq-revoked")
    _prepare_faq(fx, event_id)
    fx.faqs.disable_active("registration.status")
    publisher = FakePublisher()

    with pytest.raises(PublishingNotEligible, match="revoked"):
        asyncio.run(fx.service(publisher).dispatch_origin(event_id))

    assert publisher.calls == []
    assert fx.publications.count_actions() == 0


def test_supervisor_publishes_exact_human_response(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="supervisor", target="fb-comment-2")
    answer = "هذا رد بشري معتمد حرفيًا."
    _prepare_supervisor(fx, event_id, answer)
    publisher = FakePublisher()

    asyncio.run(fx.service(publisher).dispatch_origin(event_id))

    assert publisher.calls == [("fb-comment-2", answer)]


def test_fatwa_origin_is_blocked_by_default_policy(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="fatwa-default")
    _prepare_fatwa(fx, event_id)
    publisher = FakePublisher()

    with pytest.raises(PublishingNotEligible, match="policy"):
        asyncio.run(fx.service(publisher).dispatch_origin(event_id))

    assert publisher.calls == []
    assert fx.publications.count_actions() == 0


def test_fatwa_origin_policy_can_publish_only_exact_external_approved_text(
    tmp_path: Path,
) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="fatwa-origin", target="fb-comment-fatwa")
    answer = "نص الجواب القادم من الجهة الشرعية دون تعديل."
    _prepare_fatwa(fx, event_id, answer)
    publisher = FakePublisher()
    service = fx.service(
        publisher,
        fatwa_policy=FatwaPublicationPolicy.ORIGIN_ONLY,
    )

    asyncio.run(service.dispatch_origin(event_id))

    assert publisher.calls == [("fb-comment-fatwa", answer)]


def test_missing_origin_target_is_not_publishable(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="no-target", target=None)
    _prepare_supervisor(fx, event_id)
    publisher = FakePublisher()

    with pytest.raises(PublishingNotEligible, match="target"):
        asyncio.run(fx.service(publisher).dispatch_origin(event_id))

    assert publisher.calls == []


def test_duplicate_after_success_does_not_call_provider_twice(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="duplicate-success")
    _prepare_supervisor(fx, event_id)
    publisher = FakePublisher()
    service = fx.service(publisher)

    first = asyncio.run(service.dispatch_origin(event_id))
    second = asyncio.run(service.dispatch_origin(event_id))

    assert first.action.id == second.action.id
    assert first.provider_called is True
    assert second.provider_called is False
    assert len(publisher.calls) == 1
    assert fx.publications.count_actions() == 1


def test_provider_exception_becomes_uncertain_and_is_never_blindly_retried(
    tmp_path: Path,
) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="uncertain")
    _prepare_supervisor(fx, event_id)
    publisher = FakePublisher(fail=True)
    service = fx.service(publisher)

    with pytest.raises(PublicationUncertain):
        asyncio.run(service.dispatch_origin(event_id))
    with pytest.raises(PublicationUncertain, match="reconciliation"):
        asyncio.run(service.dispatch_origin(event_id))

    assert len(publisher.calls) == 1
    with fx.database.connect() as connection:
        row = connection.execute("SELECT status FROM outbound_actions").fetchone()
    assert row is not None
    assert row["status"] == PublicationStatus.UNCERTAIN.value


def test_concurrent_dispatch_calls_make_at_most_one_provider_call(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="concurrent")
    _prepare_supervisor(fx, event_id)
    publisher = FakePublisher(delay=0.03)
    service = fx.service(publisher)

    async def run_two() -> list[object]:
        return await asyncio.gather(
            service.dispatch_origin(event_id),
            service.dispatch_origin(event_id),
            return_exceptions=True,
        )

    outcomes = asyncio.run(run_two())

    assert len(publisher.calls) == 1
    assert fx.publications.count_actions() == 1
    assert any(not isinstance(item, Exception) for item in outcomes)
    assert any(isinstance(item, PublicationInFlight) for item in outcomes)


@pytest.mark.parametrize("platform", list(Platform))
def test_all_v1_platforms_select_matching_injected_publisher(
    tmp_path: Path,
    platform: Platform,
) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(
        key=f"platform-{platform.value}",
        platform=platform,
        target=f"target-{platform.value}",
    )
    _prepare_supervisor(fx, event_id, answer=f"رد {platform.value}")
    publisher = FakePublisher()

    asyncio.run(fx.service(publisher, platform=platform).dispatch_origin(event_id))

    assert publisher.calls == [(f"target-{platform.value}", f"رد {platform.value}")]


def test_publication_action_binds_exact_source_evidence(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="evidence-key")
    _prepare_supervisor(fx, event_id)
    publisher = FakePublisher()

    result = asyncio.run(fx.service(publisher).dispatch_origin(event_id))

    response = fx.supervisors.get_response(fx.supervisors.get_for_event(event_id).id)  # type: ignore[union-attr]
    assert response is not None
    assert response.id in result.action.action_type
    assert response.id in result.action.idempotency_key
    assert event_id in result.action.idempotency_key


def test_no_publishable_evidence_creates_no_outbound_action(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    event_id = fx.ingest(key="not-ready")
    fx.classify(event_id, ClassificationRoute.SUPERVISOR)
    publisher = FakePublisher()

    with pytest.raises(PublishingNotEligible):
        asyncio.run(fx.service(publisher).dispatch_origin(event_id))

    assert fx.publications.count_actions() == 0
    assert publisher.calls == []
