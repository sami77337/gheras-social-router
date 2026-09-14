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
from app.domain.faq import FAQResolutionStatus
from app.domain.supervisor import (
    SupervisorEscalationSource,
    SupervisorEscalationStatus,
)
from app.persistence.classification_repository import ClassificationRepository
from app.persistence.faq_repository import FAQRepository
from app.persistence.repositories import DurableRepository
from app.persistence.sqlite import SQLiteDatabase
from app.persistence.supervisor_repository import (
    SupervisorEscalationConflict,
    SupervisorRepository,
    SupervisorResponseConflict,
)
from app.services.faq import FAQService
from app.services.ingestion import IngestionService
from app.services.supervisor import (
    SupervisorDispatchNotReady,
    SupervisorNotEligible,
    SupervisorService,
)


def _build(
    tmp_path: Path,
) -> tuple[
    SQLiteDatabase,
    DurableRepository,
    ClassificationRepository,
    FAQRepository,
    SupervisorRepository,
    SupervisorService,
]:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()
    events = DurableRepository(database)
    classifications = ClassificationRepository(database)
    faqs = FAQRepository(database)
    supervisors = SupervisorRepository(database)
    service = SupervisorService(
        events=events,
        classifications=classifications,
        faqs=faqs,
        supervisors=supervisors,
    )
    return database, events, classifications, faqs, supervisors, service


def _ingest(
    events: DurableRepository,
    *,
    key: str,
    platform: Platform = Platform.FACEBOOK,
    text: str | None = "أحتاج مساعدة من المشرف",
) -> str:
    return IngestionService(events).ingest_event(
        NormalizedInboundEvent(
            platform=platform,
            external_event_key=key,
            text=text,
        )
    ).event.id


def _classify_supervisor(
    classifications: ClassificationRepository,
    event_id: str,
) -> str:
    result = classifications.create_for_event(
        event_id=event_id,
        decision=ClassificationDecision(
            route=ClassificationRoute.SUPERVISOR,
            reasons=(ClassificationReason.EXPLICIT_SUPERVISOR,),
        ),
        religious_possible=False,
        confidence=0.99,
        adapter_name="test-classifier",
        adapter_version="1",
    )
    return result.id


def _classify_fatwa(
    classifications: ClassificationRepository,
    event_id: str,
) -> None:
    classifications.create_for_event(
        event_id=event_id,
        decision=ClassificationDecision(
            route=ClassificationRoute.FATWA,
            reasons=(ClassificationReason.RELIGIOUS_SAFETY_OVERRIDE,),
        ),
        religious_possible=True,
        confidence=0.99,
        adapter_name="test-classifier",
        adapter_version="1",
    )


def _classify_faq(
    classifications: ClassificationRepository,
    event_id: str,
    *,
    faq_key: str,
) -> None:
    classifications.create_for_event(
        event_id=event_id,
        decision=ClassificationDecision(
            route=ClassificationRoute.FAQ,
            reasons=(ClassificationReason.CONFIDENT_FAQ,),
            faq_key=faq_key,
        ),
        religious_possible=False,
        confidence=0.99,
        adapter_name="test-classifier",
        adapter_version="1",
    )


def test_supervisor_classification_creates_durable_escalation(tmp_path: Path) -> None:
    _, events, classifications, _, supervisors, service = _build(tmp_path)
    event_id = _ingest(events, key="supervisor-route")
    classification_id = _classify_supervisor(classifications, event_id)

    escalation = service.ensure_escalation(event_id)

    assert escalation.source is SupervisorEscalationSource.CLASSIFICATION
    assert escalation.source_result_id == classification_id
    assert escalation.status is SupervisorEscalationStatus.PENDING_DISPATCH
    assert escalation.dispatch_attempt_count == 0
    assert supervisors.count_escalations() == 1


def test_missing_faq_entry_escalates_from_faq_resolution(tmp_path: Path) -> None:
    _, events, classifications, faqs, _, service = _build(tmp_path)
    event_id = _ingest(events, key="faq-fallback")
    _classify_faq(classifications, event_id, faq_key="missing.key")
    resolution = FAQService(classifications=classifications, faqs=faqs).resolve(event_id)
    assert resolution.resolution.status is FAQResolutionStatus.SUPERVISOR_REQUIRED

    escalation = service.ensure_escalation(event_id)

    assert escalation.source is SupervisorEscalationSource.FAQ_RESOLUTION
    assert escalation.source_result_id == resolution.resolution.id


def test_fatwa_route_is_not_supervisor_eligible(tmp_path: Path) -> None:
    _, events, classifications, _, supervisors, service = _build(tmp_path)
    event_id = _ingest(events, key="fatwa-route", text="ما حكم هذا؟")
    _classify_fatwa(classifications, event_id)

    with pytest.raises(SupervisorNotEligible):
        service.ensure_escalation(event_id)

    assert supervisors.count_escalations() == 0


def test_resolved_faq_is_not_supervisor_eligible(tmp_path: Path) -> None:
    _, events, classifications, faqs, supervisors, service = _build(tmp_path)
    event_id = _ingest(events, key="resolved-faq")
    _classify_faq(classifications, event_id, faq_key="registration.status")
    faqs.create_version(
        faq_key="registration.status",
        answer_text="التسجيل مفتوح.",
        source_ref="fixture://approved/registration",
        approved_by="reviewer-1",
        approved_at=datetime(2026, 9, 10, 7, 0, tzinfo=UTC),
    )
    resolution = FAQService(classifications=classifications, faqs=faqs).resolve(event_id)
    assert resolution.resolution.status is FAQResolutionStatus.RESOLVED

    with pytest.raises(SupervisorNotEligible):
        service.ensure_escalation(event_id)

    assert supervisors.count_escalations() == 0


def test_prepare_dispatch_returns_minimal_normalized_payload(tmp_path: Path) -> None:
    _, events, classifications, _, _, service = _build(tmp_path)
    event_id = _ingest(
        events,
        key="dispatch-payload",
        platform=Platform.YOUTUBE,
        text="أحتاج مشرفًا",
    )
    _classify_supervisor(classifications, event_id)

    request = service.prepare_dispatch(event_id)

    assert request.event_id == event_id
    assert request.platform == "youtube"
    assert request.text == "أحتاج مشرفًا"
    assert request.correlation_id


def test_dispatch_failure_increments_attempt_without_advancing_state(tmp_path: Path) -> None:
    _, events, classifications, _, _, service = _build(tmp_path)
    event_id = _ingest(events, key="dispatch-failure")
    _classify_supervisor(classifications, event_id)

    failed = service.record_dispatch_failure(event_id)

    assert failed.status is SupervisorEscalationStatus.PENDING_DISPATCH
    assert failed.dispatch_attempt_count == 1


def test_successful_dispatch_becomes_awaiting_and_is_idempotent(tmp_path: Path) -> None:
    _, events, classifications, _, _, service = _build(tmp_path)
    event_id = _ingest(events, key="dispatch-success")
    _classify_supervisor(classifications, event_id)

    first = service.mark_dispatched(
        event_id,
        transport_name="telegram",
        external_thread_id="thread-100",
    )
    second = service.mark_dispatched(
        event_id,
        transport_name="telegram",
        external_thread_id="thread-100",
    )

    assert first.id == second.id
    assert first.status is SupervisorEscalationStatus.AWAITING_RESPONSE
    assert second.dispatch_attempt_count == 1


def test_dispatch_cannot_be_rebound_to_different_thread(tmp_path: Path) -> None:
    _, events, classifications, _, _, service = _build(tmp_path)
    event_id = _ingest(events, key="dispatch-conflict")
    _classify_supervisor(classifications, event_id)
    service.mark_dispatched(
        event_id,
        transport_name="telegram",
        external_thread_id="thread-1",
    )

    with pytest.raises(SupervisorEscalationConflict):
        service.mark_dispatched(
            event_id,
            transport_name="telegram",
            external_thread_id="thread-2",
        )


def test_response_requires_awaiting_response_state(tmp_path: Path) -> None:
    _, events, classifications, _, _, service = _build(tmp_path)
    event_id = _ingest(events, key="premature-response")
    _classify_supervisor(classifications, event_id)

    with pytest.raises(ValueError, match="awaiting_response"):
        service.accept_response(
            event_id,
            external_response_key="response-1",
            supervisor_ref="supervisor-1",
            text="الرد البشري",
            received_at=datetime(2026, 9, 10, 7, 10, tzinfo=UTC),
        )


def test_human_response_is_durable_and_duplicate_is_idempotent(tmp_path: Path) -> None:
    _, events, classifications, _, supervisors, service = _build(tmp_path)
    event_id = _ingest(events, key="human-response")
    _classify_supervisor(classifications, event_id)
    service.mark_dispatched(
        event_id,
        transport_name="telegram",
        external_thread_id="thread-200",
    )

    first = service.accept_response(
        event_id,
        external_response_key="response-200",
        supervisor_ref="supervisor-1",
        text="هذا هو الرد المعتمد من المشرف.",
        received_at=datetime(2026, 9, 10, 7, 15, tzinfo=UTC),
    )
    second = service.accept_response(
        event_id,
        external_response_key="response-200",
        supervisor_ref="supervisor-1",
        text="هذا هو الرد المعتمد من المشرف.",
        received_at=datetime(2026, 9, 10, 7, 15, tzinfo=UTC),
    )

    escalation = supervisors.get_for_event(event_id)
    assert escalation is not None
    assert escalation.status is SupervisorEscalationStatus.RESPONDED
    assert first.id == second.id
    assert first.text == "هذا هو الرد المعتمد من المشرف."


def test_second_different_response_fails_closed(tmp_path: Path) -> None:
    _, events, classifications, _, _, service = _build(tmp_path)
    event_id = _ingest(events, key="response-conflict")
    _classify_supervisor(classifications, event_id)
    service.mark_dispatched(
        event_id,
        transport_name="telegram",
        external_thread_id="thread-300",
    )
    service.accept_response(
        event_id,
        external_response_key="response-300",
        supervisor_ref="supervisor-1",
        text="الرد الأول",
        received_at=datetime(2026, 9, 10, 7, 20, tzinfo=UTC),
    )

    with pytest.raises(SupervisorResponseConflict):
        service.accept_response(
            event_id,
            external_response_key="response-301",
            supervisor_ref="supervisor-2",
            text="رد مختلف",
            received_at=datetime(2026, 9, 10, 7, 21, tzinfo=UTC),
        )


def test_concurrent_duplicate_escalation_creates_one_row(tmp_path: Path) -> None:
    _, events, classifications, _, supervisors, service = _build(tmp_path)
    event_id = _ingest(events, key="escalation-race")
    _classify_supervisor(classifications, event_id)

    def create_once(_: int) -> str:
        return service.ensure_escalation(event_id).id

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(create_once, range(20)))

    assert len(set(ids)) == 1
    assert supervisors.count_escalations() == 1


def test_concurrent_duplicate_response_creates_one_response(tmp_path: Path) -> None:
    _, events, classifications, _, supervisors, service = _build(tmp_path)
    event_id = _ingest(events, key="response-race")
    _classify_supervisor(classifications, event_id)
    escalation = service.mark_dispatched(
        event_id,
        transport_name="telegram",
        external_thread_id="thread-race",
    )

    def respond_once(_: int) -> str:
        return service.accept_response(
            event_id,
            external_response_key="response-race",
            supervisor_ref="supervisor-1",
            text="رد واحد",
            received_at=datetime(2026, 9, 10, 7, 25, tzinfo=UTC),
        ).id

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(respond_once, range(20)))

    assert len(set(ids)) == 1
    response = supervisors.get_response(escalation.id)
    assert response is not None
    assert response.id == ids[0]


@pytest.mark.parametrize("platform", list(Platform))
def test_all_v1_platforms_share_supervisor_semantics(
    tmp_path: Path,
    platform: Platform,
) -> None:
    _, events, classifications, _, _, service = _build(tmp_path)
    event_id = _ingest(
        events,
        key=f"supervisor-{platform.value}",
        platform=platform,
    )
    _classify_supervisor(classifications, event_id)

    escalation = service.ensure_escalation(event_id)

    assert escalation.status is SupervisorEscalationStatus.PENDING_DISPATCH


def test_dispatch_request_rejected_after_dispatch(tmp_path: Path) -> None:
    _, events, classifications, _, _, service = _build(tmp_path)
    event_id = _ingest(events, key="dispatch-request-state")
    _classify_supervisor(classifications, event_id)
    service.mark_dispatched(
        event_id,
        transport_name="telegram",
        external_thread_id="thread-400",
    )

    with pytest.raises(SupervisorDispatchNotReady):
        service.prepare_dispatch(event_id)


def test_supervisor_schema_has_no_raw_provider_or_secret_columns(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()

    with database.connect() as connection:
        escalation_rows = connection.execute(
            "PRAGMA table_info(supervisor_escalations)"
        ).fetchall()
        response_rows = connection.execute(
            "PRAGMA table_info(supervisor_responses)"
        ).fetchall()

    column_names = {
        str(row["name"]).lower()
        for row in (*escalation_rows, *response_rows)
    }
    forbidden = {"payload", "token", "secret", "authorization", "raw_update"}
    assert not any(fragment in name for name in column_names for fragment in forbidden)
