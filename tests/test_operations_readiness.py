from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.publishing import PublicationStatus
from app.operations.database import create_verified_backup, inspect_database
from app.operations.readiness import OperationalReadinessService
from app.persistence.sqlite import SQLiteDatabase


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _insert_event(database: SQLiteDatabase, *, event_id: str, text: str) -> None:
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
                "facebook",
                f"event-key-{event_id}",
                f"external-{event_id}",
                f"comment-{event_id}",
                "post-1",
                "author-1",
                text,
                None,
                f"correlation-{event_id}",
                "received",
                0,
                None,
                now,
                now,
            ),
        )


def _insert_publication(
    database: SQLiteDatabase,
    *,
    action_id: str,
    event_id: str,
    status: PublicationStatus,
) -> None:
    now = _timestamp()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO outbound_actions (
                id, event_id, platform, action_type, idempotency_key,
                status, external_result_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action_id,
                event_id,
                "facebook",
                f"reply:faq:evidence-{action_id}",
                f"publish-key-{action_id}",
                status.value,
                None,
                now,
                now,
            ),
        )


def test_readonly_connection_refuses_missing_database(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "missing.db")

    with pytest.raises(FileNotFoundError):
        database.connect_readonly()

    assert not database.path.exists()


def test_verified_backup_preserves_database_and_refuses_overwrite(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "source.db")
    database.initialize()
    _insert_event(database, event_id="event-1", text="private-comment-body")

    destination = tmp_path / "backups" / "snapshot.db"
    receipt = create_verified_backup(database, destination)

    assert receipt.destination == destination
    assert receipt.size_bytes > 0
    assert len(receipt.sha256) == 64
    assert receipt.integrity.acceptable
    assert inspect_database(SQLiteDatabase(destination)).acceptable
    with SQLiteDatabase(destination).connect_readonly() as connection:
        row = connection.execute("SELECT COUNT(*) FROM inbound_events").fetchone()
    assert row is not None
    assert int(row[0]) == 1

    with pytest.raises(FileExistsError):
        create_verified_backup(database, destination)


def test_failed_backup_does_not_leave_invalid_destination(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.db"
    source.write_bytes(b"not-a-sqlite-database")
    destination = tmp_path / "backup.db"

    with pytest.raises(sqlite3.DatabaseError):
        create_verified_backup(SQLiteDatabase(source), destination)

    assert not destination.exists()


def test_readiness_snapshot_is_counts_only_and_flags_publication_holds(
    tmp_path: Path,
) -> None:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()
    sensitive_text = "SECRET USER COMMENT MUST NOT APPEAR"
    _insert_event(database, event_id="event-1", text=sensitive_text)
    _insert_publication(
        database,
        action_id="action-dispatching",
        event_id="event-1",
        status=PublicationStatus.DISPATCHING,
    )
    _insert_publication(
        database,
        action_id="action-uncertain",
        event_id="event-1",
        status=PublicationStatus.UNCERTAIN,
    )

    snapshot = OperationalReadinessService(database).snapshot()

    assert snapshot.integrity.acceptable
    assert snapshot.inbound_total == 1
    assert snapshot.publications_dispatching == 1
    assert snapshot.publications_uncertain == 1
    assert snapshot.requires_operator_attention
    assert sensitive_text not in repr(snapshot)


def test_reconciliation_inventory_exposes_only_opaque_operational_fields(
    tmp_path: Path,
) -> None:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()
    sensitive_text = "do-not-surface-this-comment"
    _insert_event(database, event_id="event-1", text=sensitive_text)
    _insert_publication(
        database,
        action_id="action-pending",
        event_id="event-1",
        status=PublicationStatus.PENDING,
    )
    _insert_publication(
        database,
        action_id="action-uncertain",
        event_id="event-1",
        status=PublicationStatus.UNCERTAIN,
    )

    items = OperationalReadinessService(database).publication_reconciliation_items()

    assert len(items) == 1
    item = items[0]
    assert item.action_id == "action-uncertain"
    assert item.status is PublicationStatus.UNCERTAIN
    assert set(asdict(item)) == {"action_id", "platform", "status", "updated_at"}
    assert sensitive_text not in repr(item)
