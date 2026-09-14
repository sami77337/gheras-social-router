from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.domain.events import NormalizedInboundEvent, Platform
from app.domain.states import InvalidStateTransition, ProcessingState
from app.persistence.repositories import DurableRepository
from app.persistence.sqlite import SQLiteDatabase
from app.services.ingestion import IngestionService
from app.services.transitions import TransitionService


def _build(tmp_path: Path) -> tuple[SQLiteDatabase, DurableRepository, IngestionService]:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()
    repository = DurableRepository(database)
    return database, repository, IngestionService(repository)


def _event(
    *,
    platform: Platform = Platform.FACEBOOK,
    key: str = "event-1",
) -> NormalizedInboundEvent:
    return NormalizedInboundEvent(
        platform=platform,
        external_event_key=key,
        external_event_id=f"external-{key}",
        external_comment_id=f"comment-{key}",
        external_post_id=f"post-{key}",
        author_id="author-1",
        text="السلام عليكم",
        media={"kind": "none"},
        correlation_id="corr-1",
    )


def test_new_database_initializes_expected_tables(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()

    assert {str(row["name"]) for row in rows} >= {
        "inbound_events",
        "outbound_actions",
        "processing_attempts",
    }


def test_platform_enum_is_exactly_the_four_v1_platforms() -> None:
    assert {platform.value for platform in Platform} == {
        "facebook",
        "instagram",
        "telegram",
        "youtube",
    }


def test_first_event_insert_succeeds(tmp_path: Path) -> None:
    _, repository, service = _build(tmp_path)

    result = service.ingest_event(_event())

    assert result.created is True
    assert repository.count_events() == 1
    assert result.event.status is ProcessingState.RECEIVED


def test_same_event_inserted_100_times_results_in_one_row(tmp_path: Path) -> None:
    _, repository, service = _build(tmp_path)
    normalized = _event()

    results = [service.ingest_event(normalized) for _ in range(100)]

    assert repository.count_events() == 1
    assert sum(result.created for result in results) == 1
    assert len({result.event.id for result in results}) == 1


def test_duplicate_calls_return_same_internal_event_id(tmp_path: Path) -> None:
    _, _, service = _build(tmp_path)

    first = service.ingest_event(_event())
    second = service.ingest_event(_event())

    assert first.event.id == second.event.id
    assert first.created is True
    assert second.created is False


def test_same_external_key_on_different_platforms_is_distinct(tmp_path: Path) -> None:
    _, repository, service = _build(tmp_path)

    facebook = service.ingest_event(_event(platform=Platform.FACEBOOK, key="same"))
    youtube = service.ingest_event(_event(platform=Platform.YOUTUBE, key="same"))

    assert repository.count_events() == 2
    assert facebook.event.id != youtube.event.id


def test_invalid_transition_raises_deterministic_domain_error(tmp_path: Path) -> None:
    _, repository, service = _build(tmp_path)
    event = service.ingest_event(_event()).event
    transitions = TransitionService(repository)

    with pytest.raises(
        InvalidStateTransition,
        match="invalid transition: received -> completed",
    ):
        transitions.transition(event.id, ProcessingState.COMPLETED)


def test_valid_transitions_persist(tmp_path: Path) -> None:
    _, repository, service = _build(tmp_path)
    event = service.ingest_event(_event()).event
    transitions = TransitionService(repository)

    processing = transitions.transition(event.id, ProcessingState.PROCESSING)
    waiting = transitions.transition(processing.id, ProcessingState.WAITING_HUMAN)
    completed = transitions.transition(waiting.id, ProcessingState.COMPLETED)

    assert completed.status is ProcessingState.COMPLETED
    assert repository.get_event(event.id).status is ProcessingState.COMPLETED


def test_file_backed_database_survives_repository_recreation(tmp_path: Path) -> None:
    path = tmp_path / "router.db"
    database = SQLiteDatabase(path)
    database.initialize()
    first_repository = DurableRepository(database)
    first_service = IngestionService(first_repository)
    created = first_service.ingest_event(_event()).event

    second_database = SQLiteDatabase(path)
    second_database.initialize()
    second_repository = DurableRepository(second_database)

    recovered = second_repository.get_event(created.id)
    assert recovered.id == created.id
    assert recovered.external_event_key == created.external_event_key


def test_duplicate_outbound_idempotency_key_creates_one_action(tmp_path: Path) -> None:
    _, repository, service = _build(tmp_path)
    event = service.ingest_event(_event()).event

    first = repository.create_outbound_action(
        event_id=event.id,
        platform=Platform.FACEBOOK,
        action_type="reply",
        idempotency_key="reply:event-1",
    )
    second = repository.create_outbound_action(
        event_id=event.id,
        platform=Platform.FACEBOOK,
        action_type="reply",
        idempotency_key="reply:event-1",
    )

    assert first.created is True
    assert second.created is False
    assert first.action.id == second.action.id


def test_retryable_failure_updates_retry_metadata_and_retry_clears_schedule(
    tmp_path: Path,
) -> None:
    _, repository, service = _build(tmp_path)
    event = service.ingest_event(_event()).event
    transitions = TransitionService(repository)
    processing = transitions.transition(event.id, ProcessingState.PROCESSING)
    retry_at = datetime.now(UTC) + timedelta(minutes=5)

    failed = repository.mark_retryable_failure(processing.id, next_retry_at=retry_at)

    assert failed.status is ProcessingState.FAILED_RETRYABLE
    assert failed.retry_count == 1
    assert failed.next_retry_at == retry_at

    resumed = transitions.transition(failed.id, ProcessingState.PROCESSING)
    assert resumed.status is ProcessingState.PROCESSING
    assert resumed.retry_count == 1
    assert resumed.next_retry_at is None


def test_processing_attempts_increment_per_event(tmp_path: Path) -> None:
    _, repository, service = _build(tmp_path)
    event = service.ingest_event(_event()).event

    first = repository.record_attempt(event.id, outcome="started")
    second = repository.record_attempt(
        event.id,
        outcome="retry",
        error_code="TEMPORARY",
        error_message="sanitized temporary error",
        finished=True,
    )

    assert first.attempt_number == 1
    assert second.attempt_number == 2
    assert second.error_code == "TEMPORARY"


def test_sqlite_foreign_keys_are_active(tmp_path: Path) -> None:
    database, _, _ = _build(tmp_path)

    with database.connect() as connection:
        row = connection.execute("PRAGMA foreign_keys").fetchone()

    assert row is not None
    assert int(row[0]) == 1


def test_concurrent_duplicate_ingestion_produces_one_row(tmp_path: Path) -> None:
    _, repository, service = _build(tmp_path)
    normalized = _event(key="race")

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(lambda _: service.ingest_event(normalized), range(40)))

    assert repository.count_events() == 1
    assert sum(result.created for result in results) == 1
    assert len({result.event.id for result in results}) == 1


@pytest.mark.parametrize("platform", list(Platform))
def test_all_platforms_share_same_durable_ingestion_semantics(
    tmp_path: Path, platform: Platform
) -> None:
    _, repository, service = _build(tmp_path)

    first = service.ingest_event(_event(platform=platform, key="shared-contract"))
    duplicate = service.ingest_event(_event(platform=platform, key="shared-contract"))

    assert first.event.platform is platform
    assert duplicate.event.id == first.event.id
    assert repository.count_events() == 1


def test_youtube_normalized_event_round_trips_without_schema_fork(tmp_path: Path) -> None:
    _, repository, service = _build(tmp_path)
    normalized = NormalizedInboundEvent(
        platform=Platform.YOUTUBE,
        external_event_key="yt-comment:abc123",
        external_event_id="activity-123",
        external_comment_id="comment-123",
        external_post_id="video-123",
        author_id="channel-123",
        text="جزاكم الله خيراً",
        media={"video_id": "video-123"},
        correlation_id="corr-youtube",
    )

    result = service.ingest_event(normalized)
    loaded = repository.get_event(result.event.id)

    assert loaded.platform is Platform.YOUTUBE
    assert loaded.external_post_id == "video-123"
    assert loaded.media == {"video_id": "video-123"}
