"""SQLite persistence for auditable moderation results."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.moderation import (
    ModerationCategory,
    ModerationDecision,
    ModerationDisposition,
    ModerationReason,
    ModerationResult,
)
from app.persistence.repositories import EventNotFound
from app.persistence.sqlite import SQLiteDatabase

_MAX_ADAPTER_ID_LENGTH = 80


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _from_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _compact_identifier(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > _MAX_ADAPTER_ID_LENGTH:
        raise ValueError(f"{field} must be at most {_MAX_ADAPTER_ID_LENGTH} characters")
    if any(char.isspace() for char in normalized):
        raise ValueError(f"{field} must be a compact identifier")
    return normalized


def _result_from_row(row: sqlite3.Row) -> ModerationResult:
    raw_reasons = json.loads(str(row["reason_codes_json"]))
    raw_categories = json.loads(str(row["categories_json"]))
    if not isinstance(raw_reasons, list) or not isinstance(raw_categories, list):
        raise RuntimeError("stored moderation result has invalid normalized JSON")
    confidence = row["confidence"]
    return ModerationResult(
        id=str(row["id"]),
        event_id=str(row["event_id"]),
        disposition=ModerationDisposition(str(row["disposition"])),
        reasons=tuple(ModerationReason(str(value)) for value in raw_reasons),
        categories=tuple(ModerationCategory(str(value)) for value in raw_categories),
        adapter_name=str(row["adapter_name"]),
        adapter_version=str(row["adapter_version"]),
        confidence=float(confidence) if confidence is not None else None,
        created_at=_from_timestamp(str(row["created_at"])),
    )


class ModerationRepository:
    """Durable, idempotent storage boundary for Phase 2 moderation decisions."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get_for_event(self, event_id: str) -> ModerationResult | None:
        """Return the single persisted moderation result for an event, if present."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM moderation_results WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return _result_from_row(row) if row is not None else None

    def count_results(self) -> int:
        """Return the number of persisted moderation results."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM moderation_results"
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def create_for_event(
        self,
        *,
        event_id: str,
        decision: ModerationDecision,
        categories: tuple[ModerationCategory, ...],
        adapter_name: str,
        adapter_version: str,
        confidence: float | None,
    ) -> ModerationResult:
        """Persist one result per event and return the winner on duplicate races."""

        safe_adapter_name = _compact_identifier(adapter_name, field="adapter_name")
        safe_adapter_version = _compact_identifier(adapter_version, field="adapter_version")
        if confidence is not None and not 0.0 <= confidence <= 1.0:
            raise ValueError("moderation confidence must be between 0 and 1")

        result_id = str(uuid4())
        created_at = _utc_now()
        reasons_json = json.dumps(
            sorted(reason.value for reason in decision.reasons),
            separators=(",", ":"),
        )
        categories_json = json.dumps(
            sorted(category.value for category in categories),
            separators=(",", ":"),
        )

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            event_exists = connection.execute(
                "SELECT 1 FROM inbound_events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if event_exists is None:
                connection.rollback()
                raise EventNotFound(event_id)

            try:
                connection.execute(
                    """
                    INSERT INTO moderation_results (
                        id, event_id, disposition, reason_codes_json, categories_json,
                        adapter_name, adapter_version, confidence, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result_id,
                        event_id,
                        decision.disposition.value,
                        reasons_json,
                        categories_json,
                        safe_adapter_name,
                        safe_adapter_version,
                        confidence,
                        _to_timestamp(created_at),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM moderation_results WHERE id = ?",
                    (result_id,),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise RuntimeError("inserted moderation result could not be reloaded")
                return _result_from_row(row)
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM moderation_results WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise
                return _result_from_row(row)
