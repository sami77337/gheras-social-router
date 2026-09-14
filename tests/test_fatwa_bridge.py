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
from app.domain.fatwa import FatwaBridgeStatus, FatwaResultOutcome
from app.persistence.classification_repository import ClassificationRepository
from app.persistence.fatwa_repository import (
    FatwaBridgeConflict,
    FatwaRepository,
    FatwaResultConflict,
)
from app.persistence.repositories import DurableRepository
from app.persistence.sqlite import SQLiteDatabase
from app.services.fatwa import FatwaDispatchNotReady, FatwaNotEligible, FatwaService
from app.services.ingestion import IngestionService


def _build(
    tmp_path: Path,
) -> tuple[
    SQLiteDatabase,
    DurableRepository,
    ClassificationRepository,
    FatwaRepository,
    FatwaService,
]:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()
    events = DurableRepository(database)
    classifications = ClassificationRepository(database)
    fatwas = FatwaRepository(database)
    service = FatwaService(
        events=events,
        classifications=classifications,
        fatwas=fatwas,
    )
    return database, events, classifications, fatwas, service


def _ingest(
    events: DurableRepository,
    *,
    key: str,
    platform: Platform = Platform.FACEBOOK,
    text: str | None = "ما حكم هذا الأمر؟",
) -> str:
    return IngestionService(events).ingest_event(
        NormalizedInboundEvent(
            platform=platform,
            external_event_key=key,
            text=text,
        )
    ).event.id


def _classify(
    classifications: ClassificationRepository,
    event_id: str,
    route: ClassificationRoute,
) -> str:
    if route is ClassificationRoute.FATWA:
        decision = ClassificationDecision(
            route=route,
            reasons=(ClassificationReason.RELIGIOUS_SAFETY_OVERRIDE,),
        )
        religious = True
    elif route is ClassificationRoute.SUPERVISOR:
        decision = ClassificationDecision(
            route=route,
            reasons=(ClassificationReason.EXPLICIT_SUPERVISOR,),
        )
        religious = False
    else:
        decision = ClassificationDecision(
            route=route,
            reasons=(ClassificationReason.CONFIDENT_FAQ,),
            faq_key="fixture.key",
        )
        religious = False
    return classifications.create_for_event(
        event_id=event_id,
        decision=decision,
        religious_possible=religious,
        confidence=0.99,
        adapter_name="test-classifier",
        adapter_version="1",
    ).id


def _dispatch(service: FatwaService, event_id: str, case_id: str = "case-1") -> None:
    service.mark_dispatched(
        event_id,
        bridge_name="supervised-fatwa-system",
        external_case_id=case_id,
    )


def test_fatwa_classification_creates_one_pending_request(tmp_path: Path) -> None:
    _, events, classifications, fatwas, service = _build(tmp_path)
    event_id = _ingest(events, key="fatwa-1")
    classification_id = _classify(classifications, event_id, ClassificationRoute.FATWA)

    request = service.ensure_request(event_id)

    assert request.classification_result_id == classification_id
    assert request.status is FatwaBridgeStatus.PENDING_DISPATCH
    assert request.dispatch_attempt_count == 0
    assert fatwas.count_requests() == 1


@pytest.mark.parametrize(
    "route",
    [ClassificationRoute.SUPERVISOR, ClassificationRoute.FAQ],
)
def test_non_fatwa_routes_are_not_eligible(tmp_path: Path, route: ClassificationRoute) -> None:
    _, events, classifications, fatwas, service = _build(tmp_path)
    event_id = _ingest(events, key=f"not-fatwa-{route.value}")
    _classify(classifications, event_id, route)

    with pytest.raises(FatwaNotEligible):
        service.ensure_request(event_id)

    assert fatwas.count_requests() == 0


def test_repository_cannot_bypass_fatwa_eligibility(tmp_path: Path) -> None:
    _, events, classifications, fatwas, _ = _build(tmp_path)
    event_id = _ingest(events, key="repo-gate")
    classification_id = _classify(
        classifications,
        event_id,
        ClassificationRoute.SUPERVISOR,
    )

    with pytest.raises(ValueError, match="not eligible"):
        fatwas.create_request(
            event_id=event_id,
            classification_result_id=classification_id,
        )


def test_prepare_dispatch_is_minimal_and_preserves_question(tmp_path: Path) -> None:
    _, events, classifications, _, service = _build(tmp_path)
    text = "ما حكم المعاملة بهذه الصورة؟"
    event_id = _ingest(
        events,
        key="dispatch-payload",
        platform=Platform.YOUTUBE,
        text=text,
    )
    _classify(classifications, event_id, ClassificationRoute.FATWA)

    dispatch = service.prepare_dispatch(event_id)

    assert dispatch.event_id == event_id
    assert dispatch.platform == "youtube"
    assert dispatch.question_text == text
    assert dispatch.correlation_id


def test_dispatch_failure_does_not_advance_state(tmp_path: Path) -> None:
    _, events, classifications, _, service = _build(tmp_path)
    event_id = _ingest(events, key="dispatch-failure")
    _classify(classifications, event_id, ClassificationRoute.FATWA)

    request = service.record_dispatch_failure(event_id)

    assert request.status is FatwaBridgeStatus.PENDING_DISPATCH
    assert request.dispatch_attempt_count == 1


def test_dispatch_is_idempotent_and_conflicting_case_fails(tmp_path: Path) -> None:
    _, events, classifications, _, service = _build(tmp_path)
    event_id = _ingest(events, key="dispatch-idempotency")
    _classify(classifications, event_id, ClassificationRoute.FATWA)

    first = service.mark_dispatched(
        event_id,
        bridge_name="supervised-fatwa-system",
        external_case_id="case-100",
    )
    second = service.mark_dispatched(
        event_id,
        bridge_name="supervised-fatwa-system",
        external_case_id="case-100",
    )

    assert first.id == second.id
    assert second.status is FatwaBridgeStatus.AWAITING_RESULT
    assert second.dispatch_attempt_count == 1

    with pytest.raises(FatwaBridgeConflict):
        service.mark_dispatched(
            event_id,
            bridge_name="supervised-fatwa-system",
            external_case_id="case-101",
        )


def test_prepare_dispatch_rejected_after_successful_dispatch(tmp_path: Path) -> None:
    _, events, classifications, _, service = _build(tmp_path)
    event_id = _ingest(events, key="dispatch-state")
    _classify(classifications, event_id, ClassificationRoute.FATWA)
    _dispatch(service, event_id)

    with pytest.raises(FatwaDispatchNotReady):
        service.prepare_dispatch(event_id)


def test_result_requires_awaiting_state(tmp_path: Path) -> None:
    _, events, classifications, _, service = _build(tmp_path)
    event_id = _ingest(events, key="early-result")
    _classify(classifications, event_id, ClassificationRoute.FATWA)

    with pytest.raises(ValueError, match="awaiting_result"):
        service.accept_result(
            event_id,
            external_result_key="result-1",
            outcome=FatwaResultOutcome.REJECTED,
            answer_text=None,
            approved_by=None,
            source_ref="fixture://fatwa/result-1",
            received_at=datetime(2026, 9, 10, 8, 0, tzinfo=UTC),
        )


def test_approved_result_requires_attribution_and_preserves_exact_text(
    tmp_path: Path,
) -> None:
    _, events, classifications, fatwas, service = _build(tmp_path)
    event_id = _ingest(events, key="approved-result")
    _classify(classifications, event_id, ClassificationRoute.FATWA)
    _dispatch(service, event_id)
    answer = "هذا نص الجواب المعتمد كما ورد من الجهة الشرعية."

    result = service.accept_result(
        event_id,
        external_result_key="result-approved",
        outcome=FatwaResultOutcome.APPROVED,
        answer_text=answer,
        approved_by="scholar-reviewer-1",
        source_ref="fixture://fatwa/approved-result",
        received_at=datetime(2026, 9, 10, 8, 5, tzinfo=UTC),
    )

    request = fatwas.get_for_event(event_id)
    assert request is not None
    assert request.status is FatwaBridgeStatus.APPROVED_RESULT
    assert result.publishable_answer == answer
    assert service.get_publishable_answer(event_id) == answer


@pytest.mark.parametrize(
    ("answer_text", "approved_by"),
    [(None, "reviewer"), ("جواب", None), ("   ", "reviewer")],
)
def test_approved_result_missing_evidence_fails_closed(
    tmp_path: Path,
    answer_text: str | None,
    approved_by: str | None,
) -> None:
    _, events, classifications, _, service = _build(tmp_path)
    event_id = _ingest(events, key=f"bad-approved-{answer_text}-{approved_by}")
    _classify(classifications, event_id, ClassificationRoute.FATWA)
    _dispatch(service, event_id)

    with pytest.raises(ValueError):
        service.accept_result(
            event_id,
            external_result_key="bad-approved",
            outcome=FatwaResultOutcome.APPROVED,
            answer_text=answer_text,
            approved_by=approved_by,
            source_ref="fixture://fatwa/bad",
            received_at=datetime(2026, 9, 10, 8, 10, tzinfo=UTC),
        )

    assert service.get_publishable_answer(event_id) is None


def test_rejected_result_carries_no_publishable_answer(tmp_path: Path) -> None:
    _, events, classifications, fatwas, service = _build(tmp_path)
    event_id = _ingest(events, key="rejected-result")
    _classify(classifications, event_id, ClassificationRoute.FATWA)
    _dispatch(service, event_id)

    result = service.accept_result(
        event_id,
        external_result_key="result-rejected",
        outcome=FatwaResultOutcome.REJECTED,
        answer_text=None,
        approved_by=None,
        source_ref="fixture://fatwa/rejected-result",
        received_at=datetime(2026, 9, 10, 8, 15, tzinfo=UTC),
    )

    request = fatwas.get_for_event(event_id)
    assert request is not None
    assert request.status is FatwaBridgeStatus.REJECTED
    assert result.publishable_answer is None
    assert service.get_publishable_answer(event_id) is None


def test_rejected_result_rejects_answer_text(tmp_path: Path) -> None:
    _, events, classifications, _, service = _build(tmp_path)
    event_id = _ingest(events, key="rejected-with-answer")
    _classify(classifications, event_id, ClassificationRoute.FATWA)
    _dispatch(service, event_id)

    with pytest.raises(ValueError, match="must not contain"):
        service.accept_result(
            event_id,
            external_result_key="bad-rejected",
            outcome=FatwaResultOutcome.REJECTED,
            answer_text="نص غير مسموح",
            approved_by=None,
            source_ref="fixture://fatwa/rejected",
            received_at=datetime(2026, 9, 10, 8, 20, tzinfo=UTC),
        )


def test_duplicate_identical_result_is_idempotent(tmp_path: Path) -> None:
    _, events, classifications, _, service = _build(tmp_path)
    event_id = _ingest(events, key="result-idempotent")
    _classify(classifications, event_id, ClassificationRoute.FATWA)
    _dispatch(service, event_id)
    kwargs = dict(
        external_result_key="result-same",
        outcome=FatwaResultOutcome.APPROVED,
        answer_text="جواب معتمد",
        approved_by="reviewer-1",
        source_ref="fixture://fatwa/same",
        received_at=datetime(2026, 9, 10, 8, 25, tzinfo=UTC),
    )

    first = service.accept_result(event_id, **kwargs)
    second = service.accept_result(event_id, **kwargs)

    assert first.id == second.id


def test_conflicting_second_result_fails_closed(tmp_path: Path) -> None:
    _, events, classifications, _, service = _build(tmp_path)
    event_id = _ingest(events, key="result-conflict")
    _classify(classifications, event_id, ClassificationRoute.FATWA)
    _dispatch(service, event_id)
    service.accept_result(
        event_id,
        external_result_key="result-first",
        outcome=FatwaResultOutcome.APPROVED,
        answer_text="الجواب الأول",
        approved_by="reviewer-1",
        source_ref="fixture://fatwa/first",
        received_at=datetime(2026, 9, 10, 8, 30, tzinfo=UTC),
    )

    with pytest.raises(FatwaResultConflict):
        service.accept_result(
            event_id,
            external_result_key="result-second",
            outcome=FatwaResultOutcome.APPROVED,
            answer_text="جواب مختلف",
            approved_by="reviewer-2",
            source_ref="fixture://fatwa/second",
            received_at=datetime(2026, 9, 10, 8, 31, tzinfo=UTC),
        )


def test_concurrent_duplicate_request_converges(tmp_path: Path) -> None:
    _, events, classifications, fatwas, service = _build(tmp_path)
    event_id = _ingest(events, key="request-race")
    _classify(classifications, event_id, ClassificationRoute.FATWA)

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(lambda _: service.ensure_request(event_id).id, range(20)))

    assert len(set(ids)) == 1
    assert fatwas.count_requests() == 1


def test_concurrent_identical_results_converge(tmp_path: Path) -> None:
    _, events, classifications, _, service = _build(tmp_path)
    event_id = _ingest(events, key="result-race")
    _classify(classifications, event_id, ClassificationRoute.FATWA)
    _dispatch(service, event_id)

    def accept(_: int) -> str:
        return service.accept_result(
            event_id,
            external_result_key="result-race",
            outcome=FatwaResultOutcome.APPROVED,
            answer_text="نص معتمد واحد",
            approved_by="reviewer-1",
            source_ref="fixture://fatwa/race",
            received_at=datetime(2026, 9, 10, 8, 35, tzinfo=UTC),
        ).id

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(accept, range(20)))

    assert len(set(ids)) == 1


@pytest.mark.parametrize("platform", list(Platform))
def test_all_v1_platforms_share_fatwa_bridge_semantics(
    tmp_path: Path,
    platform: Platform,
) -> None:
    _, events, classifications, _, service = _build(tmp_path)
    event_id = _ingest(events, key=f"fatwa-{platform.value}", platform=platform)
    _classify(classifications, event_id, ClassificationRoute.FATWA)

    request = service.ensure_request(event_id)

    assert request.status is FatwaBridgeStatus.PENDING_DISPATCH


def test_fatwa_tables_do_not_store_raw_provider_or_model_fields(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()

    with database.connect() as connection:
        request_columns = connection.execute(
            "PRAGMA table_info(fatwa_bridge_requests)"
        ).fetchall()
        result_columns = connection.execute(
            "PRAGMA table_info(fatwa_bridge_results)"
        ).fetchall()

    names = {str(row["name"]).lower() for row in (*request_columns, *result_columns)}
    forbidden = {"payload", "token", "secret", "authorization", "prompt", "generated"}
    assert not any(fragment in name for name in names for fragment in forbidden)
