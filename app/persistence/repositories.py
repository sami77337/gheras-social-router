"""Repositories for durable inbound events, attempts, and outbound actions."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.domain.events import (
    InboundEvent,
    NormalizedInboundEvent,
    OutboundAction,
    OutboundActionResult,
    Platform,
    ProcessingAttempt,
)
from app.domain.states import ProcessingState, validate_transition
from app.persistence.sqlite import SQLiteDatabase

_MAX_ERROR_CODE_LENGTH = 64
_MAX_ERROR_MESSAGE_LENGTH = 512
_BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(authorization|api[_-]?key|access[_-]?token|secret|password|passwd|token)"
    r"\b\s*[:=]\s*[\"']?[^,\s;\"']+[\"']?"
)
_OPENAI_STYLE_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b")
_TELEGRAM_STYLE_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")


class EventNotFound(LookupError):
    """Raised when a requested durable event does not exist."""


class IdempotencyConflict(RuntimeError):
    """Raised when an idempotency key is reused for different outbound semantics."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _from_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _normalize_error_code(value: str | None) -> str | None:
    if value is None:
        return None
    code = value.strip()
    if not code:
        return None
    if len(code) > _MAX_ERROR_CODE_LENGTH or any(char.isspace() for char in code):
        raise ValueError("error_code must be a compact identifier of at most 64 characters")
    return code


def _sanitize_error_message(value: str | None) -> str | None:
    """Reduce diagnostics to a bounded single-line summary and redact common secrets."""

    if value is None:
        return None
    sanitized = " ".join(value.split())
    if not sanitized:
        return None
    sanitized = _BEARER_TOKEN_RE.sub("Bearer [REDACTED]", sanitized)
    sanitized = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}=[REDACTED]",
        sanitized,
    )
    sanitized = _OPENAI_STYLE_KEY_RE.sub("[REDACTED]", sanitized)
    sanitized = _TELEGRAM_STYLE_TOKEN_RE.sub("[REDACTED]", sanitized)
    if len(sanitized) > _MAX_ERROR_MESSAGE_LENGTH:
        sanitized = sanitized[: _MAX_ERROR_MESSAGE_LENGTH - 3] + "..."
    return sanitized


def _event_from_row(row: sqlite3.Row) -> InboundEvent:
    raw_media = row["media_json"]
    media: dict[str, Any] | None = json.loads(raw_media) if raw_media else None
    raw_next_retry = row["next_retry_at"]
    return InboundEvent(
        id=str(row["id"]),
        platform=Platform(str(row["platform"])),
        external_event_key=str(row["external_event_key"]),
        external_event_id=row["external_event_id"],
        external_comment_id=row["external_comment_id"],
        external_post_id=row["external_post_id"],
        author_id=row["author_id"],
        text=row["text"],
        media=media,
        correlation_id=str(row["correlation_id"]),
        status=ProcessingState(str(row["status"])),
        retry_count=int(row["retry_count"]),
        next_retry_at=_from_timestamp(str(raw_next_retry)) if raw_next_retry else None,
        created_at=_from_timestamp(str(row["created_at"])),
        updated_at=_from_timestamp(str(row["updated_at"])),
    )


def _attempt_from_row(row: sqlite3.Row) -> ProcessingAttempt:
    finished_at = row["finished_at"]
    return ProcessingAttempt(
        id=str(row["id"]),
        event_id=str(row["event_id"]),
        attempt_number=int(row["attempt_number"]),
        started_at=_from_timestamp(str(row["started_at"])),
        finished_at=_from_timestamp(str(finished_at)) if finished_at else None,
        outcome=row["outcome"],
        error_code=row["error_code"],
        error_message=row["error_message"],
    )


def _action_from_row(row: sqlite3.Row) -> OutboundAction:
    return OutboundAction(
        id=str(row["id"]),
        event_id=str(row["event_id"]),
        platform=Platform(str(row["platform"])),
        action_type=str(row["action_type"]),
        idempotency_key=str(row["idempotency_key"]),
        status=str(row["status"]),
        external_result_id=row["external_result_id"],
        created_at=_from_timestamp(str(row["created_at"])),
        updated_at=_from_timestamp(str(row["updated_at"])),
    )


class DurableRepository:
    """Repository boundary for Phase 1 durable processing state."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def ingest(self, normalized: NormalizedInboundEvent) -> tuple[InboundEvent, bool]:
        """Persist a normalized event once and return the existing row on duplicates."""

        now = _utc_now()
        event_id = str(uuid4())
        correlation_id = normalized.correlation_id or str(uuid4())
        media_json = (
            json.dumps(normalized.media, ensure_ascii=False, sort_keys=True)
            if normalized.media is not None
            else None
        )

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
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
                        normalized.platform.value,
                        normalized.external_event_key,
                        normalized.external_event_id,
                        normalized.external_comment_id,
                        normalized.external_post_id,
                        normalized.author_id,
                        normalized.text,
                        media_json,
                        correlation_id,
                        ProcessingState.RECEIVED.value,
                        0,
                        None,
                        _to_timestamp(now),
                        _to_timestamp(now),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM inbound_events WHERE id = ?", (event_id,)
                ).fetchone()
                connection.commit()
                if row is None:
                    raise RuntimeError("inserted inbound event could not be reloaded")
                return _event_from_row(row), True
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT * FROM inbound_events
                    WHERE platform = ? AND external_event_key = ?
                    """,
                    (normalized.platform.value, normalized.external_event_key),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise
                return _event_from_row(row), False

    def get_event(self, event_id: str) -> InboundEvent:
        """Load one durable event by internal id."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM inbound_events WHERE id = ?", (event_id,)
            ).fetchone()
        if row is None:
            raise EventNotFound(event_id)
        return _event_from_row(row)

    def count_events(self) -> int:
        """Return the current inbound event row count."""

        with self.database.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM inbound_events").fetchone()
        if row is None:
            return 0
        return int(row["count"])

    def transition_event(self, event_id: str, target: ProcessingState) -> InboundEvent:
        """Apply one validated state transition atomically."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM inbound_events WHERE id = ?", (event_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise EventNotFound(event_id)

            current = ProcessingState(str(row["status"]))
            validate_transition(current, target)
            now = _utc_now()
            next_retry_at = None if target is ProcessingState.PROCESSING else row["next_retry_at"]
            connection.execute(
                """
                UPDATE inbound_events
                SET status = ?, next_retry_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (target.value, next_retry_at, _to_timestamp(now), event_id),
            )
            updated = connection.execute(
                "SELECT * FROM inbound_events WHERE id = ?", (event_id,)
            ).fetchone()
            connection.commit()

        if updated is None:
            raise RuntimeError("updated inbound event could not be reloaded")
        return _event_from_row(updated)

    def mark_retryable_failure(
        self, event_id: str, *, next_retry_at: datetime
    ) -> InboundEvent:
        """Persist a retryable failure, increment retry count, and schedule eligibility."""

        if next_retry_at.tzinfo is None or next_retry_at.utcoffset() is None:
            raise ValueError("next_retry_at must be timezone-aware")
        retry_at = next_retry_at.astimezone(UTC)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM inbound_events WHERE id = ?", (event_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise EventNotFound(event_id)

            current = ProcessingState(str(row["status"]))
            validate_transition(current, ProcessingState.FAILED_RETRYABLE)
            now = _utc_now()
            connection.execute(
                """
                UPDATE inbound_events
                SET status = ?, retry_count = retry_count + 1,
                    next_retry_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    ProcessingState.FAILED_RETRYABLE.value,
                    _to_timestamp(retry_at),
                    _to_timestamp(now),
                    event_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM inbound_events WHERE id = ?", (event_id,)
            ).fetchone()
            connection.commit()

        if updated is None:
            raise RuntimeError("retryable inbound event could not be reloaded")
        return _event_from_row(updated)

    def record_attempt(
        self,
        event_id: str,
        *,
        outcome: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        finished: bool = False,
    ) -> ProcessingAttempt:
        """Append a sanitized processing attempt with a monotonic per-event number."""

        started_at = _utc_now()
        finished_at = started_at if finished else None
        attempt_id = str(uuid4())
        safe_error_code = _normalize_error_code(error_code)
        safe_error_message = _sanitize_error_message(error_message)

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                "SELECT 1 FROM inbound_events WHERE id = ?", (event_id,)
            ).fetchone()
            if exists is None:
                connection.rollback()
                raise EventNotFound(event_id)

            row = connection.execute(
                """
                SELECT COALESCE(MAX(attempt_number), 0) + 1 AS next_attempt
                FROM processing_attempts WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise RuntimeError("could not allocate attempt number")
            attempt_number = int(row["next_attempt"])

            connection.execute(
                """
                INSERT INTO processing_attempts (
                    id, event_id, attempt_number, started_at, finished_at,
                    outcome, error_code, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    event_id,
                    attempt_number,
                    _to_timestamp(started_at),
                    _to_timestamp(finished_at) if finished_at else None,
                    outcome,
                    safe_error_code,
                    safe_error_message,
                ),
            )
            created = connection.execute(
                "SELECT * FROM processing_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            connection.commit()

        if created is None:
            raise RuntimeError("inserted processing attempt could not be reloaded")
        return _attempt_from_row(created)

    def create_outbound_action(
        self,
        *,
        event_id: str,
        platform: Platform,
        action_type: str,
        idempotency_key: str,
        status: str = "pending",
    ) -> OutboundActionResult:
        """Create one outbound action idempotently by unique idempotency key."""

        if not idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")
        action_id = str(uuid4())
        now = _utc_now()

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                "SELECT 1 FROM inbound_events WHERE id = ?", (event_id,)
            ).fetchone()
            if exists is None:
                connection.rollback()
                raise EventNotFound(event_id)

            try:
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
                        platform.value,
                        action_type,
                        idempotency_key,
                        status,
                        None,
                        _to_timestamp(now),
                        _to_timestamp(now),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM outbound_actions WHERE id = ?", (action_id,)
                ).fetchone()
                connection.commit()
                if row is None:
                    raise RuntimeError("inserted outbound action could not be reloaded")
                return OutboundActionResult(_action_from_row(row), True
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM outbound_actions WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise
                existing = _action_from_row(row)
                if (
                    existing.event_id != event_id
                    or existing.platform is not platform
                    or existing.action_type != action_type
                ):
                    raise IdempotencyConflict(
                        "idempotency_key is already bound to a different outbound action"
                    ) from None
                return OutboundActionResult(existing, False)
