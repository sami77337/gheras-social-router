from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import pytest

from app.adapters.contracts import ClassificationAdapter
from app.domain.classification import (
    ClassificationAssessment,
    ClassificationReason,
    ClassificationRequest,
    ClassificationRoute,
)
from app.domain.events import NormalizedInboundEvent, Platform
from app.domain.moderation import (
    ModerationDecision,
    ModerationDisposition,
    ModerationReason,
)
from app.persistence.classification_repository import ClassificationRepository
from app.persistence.moderation_repository import ModerationRepository
from app.persistence.repositories import DurableRepository
from app.persistence.sqlite import SQLiteDatabase
from app.services.classification import ClassificationNotEligible, ClassificationService
from app.services.classification_policy import ClassificationPolicy
from app.services.ingestion import IngestionService


class StaticClassificationAdapter:
    name = "test-classifier"
    version = "1"

    def __init__(self, assessment: ClassificationAssessment) -> None:
        self.assessment = assessment
        self.calls = 0

    async def classify(self, request: ClassificationRequest) -> ClassificationAssessment:
        self.calls += 1
        return self.assessment


class RaisingClassificationAdapter:
    name = "test-failing-classifier"
    version = "1"

    async def classify(self, request: ClassificationRequest) -> ClassificationAssessment:
        raise RuntimeError("Authorization: Bearer classifier-secret-value")


class MalformedClassificationAdapter:
    name = "test-malformed-classifier"
    version = "1"

    async def classify(self, request: ClassificationRequest) -> object:
        return {"route": "FAQ", "answer": "should never be accepted"}


def _build(
    tmp_path: Path,
    adapter: ClassificationAdapter,
) -> tuple[
    SQLiteDatabase,
    DurableRepository,
    ModerationRepository,
    ClassificationRepository,
    ClassificationService,
]:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()
    events = DurableRepository(database)
    moderation = ModerationRepository(database)
    results = ClassificationRepository(database)
    service = ClassificationService(
        events=events,
        moderation=moderation,
        results=results,
        adapter=adapter,
        policy=ClassificationPolicy(minimum_faq_confidence=0.80),
    )
    return database, events, moderation, results, service


def _ingest(
    events: DurableRepository,
    *,
    platform: Platform = Platform.FACEBOOK,
    key: str = "classification-event",
    text: str | None = "متى يبدأ التسجيل؟",
) -> str:
    return IngestionService(events).ingest_event(
        NormalizedInboundEvent(
            platform=platform,
            external_event_key=key,
            text=text,
        )
    ).event.id


def _persist_moderation(
    moderation: ModerationRepository,
    event_id: str,
    disposition: ModerationDisposition,
) -> None:
    reason = (
        ModerationReason.EXPLICIT_SAFE
        if disposition is ModerationDisposition.ALLOW_ROUTING
        else ModerationReason.EXPLICIT_UNSAFE
    )
    moderation.create_for_event(
        event_id=event_id,
        decision=ModerationDecision(disposition=disposition, reasons=(reason,)),
        categories=(),
        adapter_name="test-moderation",
        adapter_version="1",
        confidence=0.99,
    )


def _faq_assessment(
    *,
    confidence: float = 0.99,
    religious_possible: bool = False,
    faq_key: str | None = "registration.status",
) -> ClassificationAssessment:
    return ClassificationAssessment(
        proposed_route=ClassificationRoute.FAQ,
        confidence=confidence,
        religious_possible=religious_possible,
        faq_key=faq_key,
    )


def test_confident_faq_with_valid_key_routes_to_faq(tmp_path: Path) -> None:
    adapter = StaticClassificationAdapter(_faq_assessment())
    _, events, moderation, results, service = _build(tmp_path, adapter)
    event_id = _ingest(events)
    _persist_moderation(moderation, event_id, ModerationDisposition.ALLOW_ROUTING)

    result = asyncio.run(service.classify(event_id))

    assert result.route is ClassificationRoute.FAQ
    assert result.faq_key == "registration.status"
    assert result.reasons == (ClassificationReason.CONFIDENT_FAQ,)
    assert results.count_results() == 1


def test_low_confidence_faq_routes_to_supervisor(tmp_path: Path) -> None:
    adapter = StaticClassificationAdapter(_faq_assessment(confidence=0.40))
    _, events, moderation, _, service = _build(tmp_path, adapter)
    event_id = _ingest(events)
    _persist_moderation(moderation, event_id, ModerationDisposition.ALLOW_ROUTING)

    result = asyncio.run(service.classify(event_id))

    assert result.route is ClassificationRoute.SUPERVISOR
    assert result.faq_key is None
    assert result.reasons == (ClassificationReason.LOW_CONFIDENCE,)


def test_faq_without_key_routes_to_supervisor(tmp_path: Path) -> None:
    adapter = StaticClassificationAdapter(_faq_assessment(faq_key=None))
    _, events, moderation, _, service = _build(tmp_path, adapter)
    event_id = _ingest(events)
    _persist_moderation(moderation, event_id, ModerationDisposition.ALLOW_ROUTING)

    result = asyncio.run(service.classify(event_id))

    assert result.route is ClassificationRoute.SUPERVISOR
    assert result.reasons == (ClassificationReason.FAQ_KEY_MISSING,)


def test_religious_possible_overrides_faq_to_fatwa(tmp_path: Path) -> None:
    adapter = StaticClassificationAdapter(_faq_assessment(religious_possible=True))
    _, events, moderation, _, service = _build(tmp_path, adapter)
    event_id = _ingest(events, key="religious-override", text="ما حكم هذا الأمر؟")
    _persist_moderation(moderation, event_id, ModerationDisposition.ALLOW_ROUTING)

    result = asyncio.run(service.classify(event_id))

    assert result.route is ClassificationRoute.FATWA
    assert result.faq_key is None
    assert result.religious_possible is True
    assert result.reasons == (ClassificationReason.RELIGIOUS_SAFETY_OVERRIDE,)


def test_religious_possible_overrides_missing_text_to_fatwa(tmp_path: Path) -> None:
    adapter = StaticClassificationAdapter(_faq_assessment(religious_possible=True))
    _, events, moderation, _, service = _build(tmp_path, adapter)
    event_id = _ingest(events, key="religious-no-text", text="   ")
    _persist_moderation(moderation, event_id, ModerationDisposition.ALLOW_ROUTING)

    result = asyncio.run(service.classify(event_id))

    assert result.route is ClassificationRoute.FATWA
    assert result.reasons == (ClassificationReason.RELIGIOUS_SAFETY_OVERRIDE,)


def test_explicit_fatwa_route_is_preserved(tmp_path: Path) -> None:
    assessment = ClassificationAssessment(
        proposed_route=ClassificationRoute.FATWA,
        confidence=0.55,
        religious_possible=False,
    )
    adapter = StaticClassificationAdapter(assessment)
    _, events, moderation, _, service = _build(tmp_path, adapter)
    event_id = _ingest(events, key="explicit-fatwa", text="سؤال يحتاج فتوى")
    _persist_moderation(moderation, event_id, ModerationDisposition.ALLOW_ROUTING)

    result = asyncio.run(service.classify(event_id))

    assert result.route is ClassificationRoute.FATWA
    assert result.reasons == (ClassificationReason.EXPLICIT_FATWA,)


def test_explicit_supervisor_route_is_preserved(tmp_path: Path) -> None:
    assessment = ClassificationAssessment(
        proposed_route=ClassificationRoute.SUPERVISOR,
        confidence=0.99,
        religious_possible=False,
    )
    adapter = StaticClassificationAdapter(assessment)
    _, events, moderation, _, service = _build(tmp_path, adapter)
    event_id = _ingest(events, key="explicit-supervisor")
    _persist_moderation(moderation, event_id, ModerationDisposition.ALLOW_ROUTING)

    result = asyncio.run(service.classify(event_id))

    assert result.route is ClassificationRoute.SUPERVISOR
    assert result.reasons == (ClassificationReason.EXPLICIT_SUPERVISOR,)


def test_adapter_failure_routes_to_supervisor_without_secret_persistence(
    tmp_path: Path,
) -> None:
    database, events, moderation, results, service = _build(
        tmp_path,
        RaisingClassificationAdapter(),
    )
    event_id = _ingest(events, key="classifier-failure")
    _persist_moderation(moderation, event_id, ModerationDisposition.ALLOW_ROUTING)

    result = asyncio.run(service.classify(event_id))

    assert result.route is ClassificationRoute.SUPERVISOR
    assert result.reasons == (ClassificationReason.ADAPTER_FAILURE,)
    assert result.confidence is None
    assert results.count_results() == 1
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM classification_results WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    assert row is not None
    assert "classifier-secret-value" not in " ".join(str(value) for value in tuple(row))


def test_malformed_adapter_result_routes_to_supervisor(tmp_path: Path) -> None:
    adapter = cast(ClassificationAdapter, MalformedClassificationAdapter())
    _, events, moderation, _, service = _build(tmp_path, adapter)
    event_id = _ingest(events, key="malformed-classifier")
    _persist_moderation(moderation, event_id, ModerationDisposition.ALLOW_ROUTING)

    result = asyncio.run(service.classify(event_id))

    assert result.route is ClassificationRoute.SUPERVISOR
    assert result.reasons == (ClassificationReason.INVALID_ASSESSMENT,)
    assert result.confidence is None


@pytest.mark.parametrize(
    "disposition",
    [
        None,
        ModerationDisposition.HUMAN_REVIEW,
        ModerationDisposition.BLOCK_ROUTING,
    ],
)
def test_classification_requires_allow_routing_moderation(
    tmp_path: Path,
    disposition: ModerationDisposition | None,
) -> None:
    adapter = StaticClassificationAdapter(_faq_assessment())
    _, events, moderation, results, service = _build(tmp_path, adapter)
    event_id = _ingest(events, key=f"moderation-gate-{disposition}")
    if disposition is not None:
        _persist_moderation(moderation, event_id, disposition)

    with pytest.raises(ClassificationNotEligible, match="allow_routing"):
        asyncio.run(service.classify(event_id))

    assert adapter.calls == 0
    assert results.count_results() == 0


@pytest.mark.parametrize("platform", list(Platform))
def test_all_v1_platforms_share_classification_semantics(
    tmp_path: Path,
    platform: Platform,
) -> None:
    adapter = StaticClassificationAdapter(_faq_assessment())
    _, events, moderation, _, service = _build(tmp_path, adapter)
    event_id = _ingest(
        events,
        platform=platform,
        key=f"classification-{platform.value}",
    )
    _persist_moderation(moderation, event_id, ModerationDisposition.ALLOW_ROUTING)

    result = asyncio.run(service.classify(event_id))

    assert result.route is ClassificationRoute.FAQ


def test_duplicate_classification_calls_reuse_result_and_adapter_call(tmp_path: Path) -> None:
    adapter = StaticClassificationAdapter(_faq_assessment())
    _, events, moderation, results, service = _build(tmp_path, adapter)
    event_id = _ingest(events, key="classification-duplicate")
    _persist_moderation(moderation, event_id, ModerationDisposition.ALLOW_ROUTING)

    first = asyncio.run(service.classify(event_id))
    second = asyncio.run(service.classify(event_id))

    assert first.id == second.id
    assert adapter.calls == 1
    assert results.count_results() == 1


def test_concurrent_duplicate_classification_creates_one_result_row(tmp_path: Path) -> None:
    adapter = StaticClassificationAdapter(_faq_assessment())
    _, events, moderation, results, service = _build(tmp_path, adapter)
    event_id = _ingest(events, key="classification-race")
    _persist_moderation(moderation, event_id, ModerationDisposition.ALLOW_ROUTING)

    def classify_once(_: int) -> str:
        return asyncio.run(service.classify(event_id)).id

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(classify_once, range(20)))

    assert len(set(ids)) == 1
    assert results.count_results() == 1


def test_no_classifiable_text_routes_to_supervisor(tmp_path: Path) -> None:
    adapter = StaticClassificationAdapter(_faq_assessment())
    _, events, moderation, _, service = _build(tmp_path, adapter)
    event_id = _ingest(events, key="empty-text", text="   ")
    _persist_moderation(moderation, event_id, ModerationDisposition.ALLOW_ROUTING)

    result = asyncio.run(service.classify(event_id))

    assert result.route is ClassificationRoute.SUPERVISOR
    assert result.reasons == (ClassificationReason.NO_CLASSIFIABLE_TEXT,)


def test_classification_result_foreign_key_is_enforced(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()

    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO classification_results (
                id, event_id, route, reason_codes_json, faq_key,
                religious_possible, confidence, adapter_name,
                adapter_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "classification-1",
                "missing-event",
                "SUPERVISOR",
                '["adapter_failure"]',
                None,
                None,
                None,
                "test-classifier",
                "1",
                "2026-09-10T07:00:00+00:00",
            ),
        )


def test_classification_schema_has_no_answer_or_raw_provider_columns(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()

    with database.connect() as connection:
        rows = connection.execute("PRAGMA table_info(classification_results)").fetchall()

    column_names = {str(row["name"]) for row in rows}
    forbidden_fragments = {"answer", "response", "payload", "prompt", "chain"}
    assert all(
        not any(fragment in name.lower() for fragment in forbidden_fragments)
        for name in column_names
    )
