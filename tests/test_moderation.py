from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import pytest

from app.adapters.contracts import ModerationAdapter
from app.domain.events import NormalizedInboundEvent, Platform
from app.domain.moderation import (
    ModerationAssessment,
    ModerationCategory,
    ModerationDisposition,
    ModerationReason,
    ModerationRequest,
    ModerationSeverity,
    ModerationVerdict,
)
from app.persistence.moderation_repository import ModerationRepository
from app.persistence.repositories import DurableRepository
from app.persistence.sqlite import SQLiteDatabase
from app.services.ingestion import IngestionService
from app.services.moderation import ModerationService
from app.services.moderation_policy import ModerationPolicy


class StaticModerationAdapter:
    name = "test-moderation"
    version = "1"

    def __init__(self, assessment: ModerationAssessment) -> None:
        self.assessment = assessment
        self.calls = 0

    async def assess(self, request: ModerationRequest) -> ModerationAssessment:
        self.calls += 1
        return self.assessment


class RaisingModerationAdapter:
    name = "test-failing-moderation"
    version = "1"

    async def assess(self, request: ModerationRequest) -> ModerationAssessment:
        raise RuntimeError("Authorization: Bearer super-secret-value")


class MalformedModerationAdapter:
    name = "test-malformed-moderation"
    version = "1"

    async def assess(self, request: ModerationRequest) -> object:
        return {"verdict": "safe"}


def _build(
    tmp_path: Path,
    adapter: ModerationAdapter,
) -> tuple[SQLiteDatabase, DurableRepository, ModerationRepository, ModerationService]:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()
    events = DurableRepository(database)
    results = ModerationRepository(database)
    service = ModerationService(
        events=events,
        results=results,
        adapter=adapter,
        policy=ModerationPolicy(minimum_confidence=0.80),
    )
    return database, events, results, service


def _ingest(
    events: DurableRepository,
    *,
    platform: Platform = Platform.FACEBOOK,
    key: str = "moderation-event",
    text: str | None = "مرحبا بكم",
    media: dict[str, object] | None = None,
) -> str:
    service = IngestionService(events)
    return service.ingest_event(
        NormalizedInboundEvent(
            platform=platform,
            external_event_key=key,
            text=text,
            media=media,
        )
    ).event.id


def _safe_assessment(
    *,
    media_assessed: bool = False,
    confidence: float = 0.99,
) -> ModerationAssessment:
    return ModerationAssessment(
        verdict=ModerationVerdict.SAFE,
        severity=ModerationSeverity.NONE,
        confidence=confidence,
        text_assessed=True,
        media_assessed=media_assessed,
    )


def test_explicit_safe_text_allows_routing(tmp_path: Path) -> None:
    adapter = StaticModerationAdapter(_safe_assessment())
    _, events, results, service = _build(tmp_path, adapter)
    event_id = _ingest(events)

    result = asyncio.run(service.moderate(event_id))

    assert result.disposition is ModerationDisposition.ALLOW_ROUTING
    assert result.reasons == (ModerationReason.EXPLICIT_SAFE,)
    assert results.count_results() == 1


def test_contradictory_safe_assessment_fails_closed(tmp_path: Path) -> None:
    assessment = ModerationAssessment(
        verdict=ModerationVerdict.SAFE,
        severity=ModerationSeverity.HIGH,
        confidence=0.99,
        categories=(ModerationCategory.HARMFUL_CONTENT,),
        text_assessed=True,
    )
    adapter = StaticModerationAdapter(assessment)
    _, events, _, service = _build(tmp_path, adapter)
    event_id = _ingest(events, key="contradictory-safe")

    result = asyncio.run(service.moderate(event_id))

    assert result.disposition is ModerationDisposition.HUMAN_REVIEW
    assert result.reasons == (ModerationReason.INVALID_ASSESSMENT,)


def test_explicit_high_severity_unsafe_content_blocks_routing(tmp_path: Path) -> None:
    assessment = ModerationAssessment(
        verdict=ModerationVerdict.UNSAFE,
        severity=ModerationSeverity.HIGH,
        confidence=0.99,
        categories=(ModerationCategory.HARMFUL_CONTENT,),
        text_assessed=True,
    )
    adapter = StaticModerationAdapter(assessment)
    _, events, _, service = _build(tmp_path, adapter)
    event_id = _ingest(events)

    result = asyncio.run(service.moderate(event_id))

    assert result.disposition is ModerationDisposition.BLOCK_ROUTING
    assert result.reasons == (ModerationReason.EXPLICIT_UNSAFE,)
    assert result.categories == (ModerationCategory.HARMFUL_CONTENT,)


def test_low_confidence_is_escalated_to_human_review(tmp_path: Path) -> None:
    adapter = StaticModerationAdapter(_safe_assessment(confidence=0.40))
    _, events, _, service = _build(tmp_path, adapter)
    event_id = _ingest(events)

    result = asyncio.run(service.moderate(event_id))

    assert result.disposition is ModerationDisposition.HUMAN_REVIEW
    assert result.reasons == (ModerationReason.LOW_CONFIDENCE,)


def test_adapter_failure_is_durable_human_review_without_exception_secret(tmp_path: Path) -> None:
    database, events, results, service = _build(tmp_path, RaisingModerationAdapter())
    event_id = _ingest(events)

    result = asyncio.run(service.moderate(event_id))

    assert result.disposition is ModerationDisposition.HUMAN_REVIEW
    assert result.reasons == (ModerationReason.ADAPTER_FAILURE,)
    assert result.confidence is None
    assert results.count_results() == 1
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM moderation_results WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    assert row is not None
    assert "super-secret-value" not in " ".join(str(value) for value in tuple(row))


def test_malformed_adapter_result_fails_closed(tmp_path: Path) -> None:
    adapter = cast(ModerationAdapter, MalformedModerationAdapter())
    _, events, _, service = _build(tmp_path, adapter)
    event_id = _ingest(events)

    result = asyncio.run(service.moderate(event_id))

    assert result.disposition is ModerationDisposition.HUMAN_REVIEW
    assert result.reasons == (ModerationReason.INVALID_ASSESSMENT,)
    assert result.confidence is None


def test_media_present_but_unassessed_cannot_be_allowed(tmp_path: Path) -> None:
    adapter = StaticModerationAdapter(_safe_assessment(media_assessed=False))
    _, events, _, service = _build(tmp_path, adapter)
    event_id = _ingest(
        events,
        media={"kind": "image", "media_ref": "normalized-ref-1"},
    )

    result = asyncio.run(service.moderate(event_id))

    assert result.disposition is ModerationDisposition.HUMAN_REVIEW
    assert ModerationReason.MEDIA_UNASSESSED in result.reasons


def test_empty_unassessable_event_goes_to_human_review(tmp_path: Path) -> None:
    assessment = ModerationAssessment(
        verdict=ModerationVerdict.SAFE,
        severity=ModerationSeverity.NONE,
        confidence=0.99,
    )
    adapter = StaticModerationAdapter(assessment)
    _, events, _, service = _build(tmp_path, adapter)
    event_id = _ingest(events, text="   ", media=None)

    result = asyncio.run(service.moderate(event_id))

    assert result.disposition is ModerationDisposition.HUMAN_REVIEW
    assert result.reasons == (ModerationReason.NO_ASSESSABLE_CONTENT,)


@pytest.mark.parametrize("platform", list(Platform))
def test_all_v1_platforms_share_the_same_moderation_semantics(
    tmp_path: Path,
    platform: Platform,
) -> None:
    adapter = StaticModerationAdapter(_safe_assessment())
    _, events, _, service = _build(tmp_path, adapter)
    event_id = _ingest(events, platform=platform, key=f"moderation-{platform.value}")

    result = asyncio.run(service.moderate(event_id))

    assert result.disposition is ModerationDisposition.ALLOW_ROUTING


def test_duplicate_moderation_calls_return_same_durable_result(tmp_path: Path) -> None:
    adapter = StaticModerationAdapter(_safe_assessment())
    _, events, results, service = _build(tmp_path, adapter)
    event_id = _ingest(events)

    first = asyncio.run(service.moderate(event_id))
    second = asyncio.run(service.moderate(event_id))

    assert first.id == second.id
    assert adapter.calls == 1
    assert results.count_results() == 1


def test_concurrent_duplicate_moderation_creates_one_result_row(tmp_path: Path) -> None:
    adapter = StaticModerationAdapter(_safe_assessment())
    _, events, results, service = _build(tmp_path, adapter)
    event_id = _ingest(events, key="moderation-race")

    def moderate_once(_: int) -> str:
        return asyncio.run(service.moderate(event_id)).id

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(moderate_once, range(20)))

    assert len(set(ids)) == 1
    assert results.count_results() == 1


def test_moderation_result_foreign_key_is_enforced(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()

    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO moderation_results (
                id, event_id, disposition, reason_codes_json, categories_json,
                adapter_name, adapter_version, confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "result-1",
                "missing-event",
                "human_review",
                '["adapter_failure"]',
                "[]",
                "test-adapter",
                "1",
                None,
                "2026-09-10T07:00:00+00:00",
            ),
        )
