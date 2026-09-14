from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.operations.shadow_evidence import ShadowEvidenceService
from app.persistence.sqlite import SQLiteDatabase


def _timestamp(offset_seconds: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset_seconds)).isoformat()


def _insert_event(database: SQLiteDatabase, *, event_id: str, platform: str) -> None:
    now = _timestamp()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO inbound_events (
                id, platform, external_event_key, external_event_id,
                external_comment_id, external_post_id, author_id, text,
                media_json, correlation_id, status, retry_count,
                next_retry_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                platform,
                f"event-key-{event_id}",
                f"external-{event_id}",
                f"comment-{event_id}",
                "post-1",
                "author-1",
                f"sensitive inbound content {event_id}",
                None,
                f"correlation-{event_id}",
                "received",
                0,
                None,
                now,
                now,
            ),
        )


def _insert_shadow(
    database: SQLiteDatabase,
    *,
    evaluation_id: str,
    event_id: str,
    platform: str,
    version: str,
    route: str | None,
    outcome: str,
    created_at: str,
    proposed_text: str | None = None,
) -> None:
    if outcome == "would_publish":
        source_kind = "faq"
        evidence_id = f"evidence-{evaluation_id}"
        text = proposed_text or f"sensitive reply {evaluation_id}"
    else:
        source_kind = None
        evidence_id = None
        text = None
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO shadow_evaluations (
                id, event_id, correlation_id, platform, evaluator_version,
                observed_route, outcome, source_kind, evidence_id,
                proposed_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation_id,
                event_id,
                f"correlation-{event_id}",
                platform,
                version,
                route,
                outcome,
                source_kind,
                evidence_id,
                text,
                created_at,
            ),
        )


def test_shadow_report_is_scoped_to_exact_evaluator_version(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()
    for event_id, platform in (
        ("event-1", "facebook"),
        ("event-2", "telegram"),
        ("event-3", "youtube"),
    ):
        _insert_event(database, event_id=event_id, platform=platform)

    first = _timestamp(0)
    second = _timestamp(1)
    _insert_shadow(
        database,
        evaluation_id="eval-1",
        event_id="event-1",
        platform="facebook",
        version="shadow-v19-a",
        route="FAQ",
        outcome="would_publish",
        created_at=first,
        proposed_text="TOP SECRET APPROVED REPLY",
    )
    _insert_shadow(
        database,
        evaluation_id="eval-2",
        event_id="event-2",
        platform="telegram",
        version="shadow-v19-a",
        route="FATWA",
        outcome="would_route_fatwa",
        created_at=second,
    )
    _insert_shadow(
        database,
        evaluation_id="eval-other",
        event_id="event-3",
        platform="youtube",
        version="shadow-v19-b",
        route=None,
        outcome="blocked",
        created_at=_timestamp(2),
    )

    report = ShadowEvidenceService(database).report("shadow-v19-a")

    assert report.total_evaluated == 2
    assert report.by_platform == {"facebook": 1, "telegram": 1}
    assert report.by_route == {"FAQ": 1, "FATWA": 1}
    assert report.by_outcome == {"would_publish": 1, "would_route_fatwa": 1}
    assert report.first_created_at.isoformat() == first
    assert report.last_created_at.isoformat() == second
    assert len(report.evidence_sha256) == 64
    assert "TOP SECRET APPROVED REPLY" not in repr(report)
    assert "TOP SECRET APPROVED REPLY" not in str(asdict(report))


def test_shadow_report_digest_is_deterministic(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()
    _insert_event(database, event_id="event-1", platform="instagram")
    _insert_shadow(
        database,
        evaluation_id="eval-1",
        event_id="event-1",
        platform="instagram",
        version="shadow-v19",
        route="SUPERVISOR",
        outcome="would_wait_human",
        created_at=_timestamp(),
    )

    service = ShadowEvidenceService(database)
    first = service.report("shadow-v19")
    second = service.report("shadow-v19")

    assert second == first
    assert second.evidence_sha256 == first.evidence_sha256


def test_shadow_report_fails_when_version_has_no_evidence(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()

    with pytest.raises(LookupError, match="no Shadow evidence"):
        ShadowEvidenceService(database).report("missing-version")


def test_shadow_report_rejects_ambiguous_version_identifier(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()

    with pytest.raises(ValueError, match="compact identifier"):
        ShadowEvidenceService(database).report("shadow version with spaces")
