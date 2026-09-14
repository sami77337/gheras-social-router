"""SQLite persistence for normalized semantic-routing results."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.classification import (
    ClassificationDecision,
    ClassificationReason,
    ClassificationResult,
    ClassificationRoute,
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


def _result_from_row(row: sqlite3.Row) -> ClassificationResult:
    raw_reasons = json.loads(str(row["reason_codes_json"]))
    if not isinstance(raw_reasons, list):
        raise RuntimeError("stored classification result has invalid normalized JSON")
    religious_raw = row["religious_possible"]
    return ClassificationResult(
        id=str(row["id"]),
        event_id=str(row["event_id"]),
        route=ClassificationRoute(str(row["route"])),
        reasons=tuple(ClassificationReason(str(value)) for value in raw_reasons),
        faq_key=row["faq_key"],
        religious_possible=(bool(int(religious_raw)) if religious_raw is not None else None),
        confidence=(float(row["confidence"]) if row["confidence"] is not None else None),
        adapter_name=str(row["adapter_name"]),
        adapter_version=str(row["adapter_version"]),
        created_at=_from_timestamp(str(row["created_at"])),
    )


class ClassificationRepository:
    """Durable idempotency boundary for one classification result per event."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get_for_event(self, event_id: str) -> ClassificationResult | None:
        """Load the durable classification result for an event, if present."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM classification_results WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return _result_from_row(row) if row is not None else None

    def count_results(self) -> int:
        """Return the number of stored classification results."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM classification_results"
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def create_for_event(
        self,
        *,
        event_id: str,
        decision: ClassificationDecision,
        religious_possible: bool | None,
        confidence: float | None,
        adapter_name: str,
        adapter_version: str,
    ) -> ClassificationResult:
        """Persist one routing result and return the winner of duplicate races."""

        safe_adapter_name = _compact_identifier(adapter_name, field="adapter_name")
        safe_adapter_version = _compact_identifier(adapter_version, field="adapter_version")
        if confidence is not None and not 0.0 <= confidence <= 1.0:
            raise ValueError("classification confidence must be between 0 and 1")

        result_id = str(uuid4())
        created_at = _utc_now()
        reasons_json = json.dumps(
            sorted(reason.value for reason in decision.reasons),
            separators=(",", ":"),
        )
        religious_db = None if religious_possible is None else int(religious_possible)

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
                    INSERT INTO classification_results (
                        id, event_id, route, reason_codes_json, faq_key,
                        religious_possible, confidence, adapter_name,
                        adapter_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result_id,
                        event_id,
                        decision.route.value,
                        reasons_json,
                        decision.faq_key,
                        religious_db,
                        confidence,
                        safe_adapter_name,
                        safe_adapter_version,
                        _to_timestamp(created_at),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM classification_results WHERE id = ?",
                    (result_id,),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise RuntimeError("inserted classification result could not be reloaded")
                return _result_from_row(row)
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM classification_results WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise
                return _result_from_row(row)
