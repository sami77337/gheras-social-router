"""SQLite persistence for the isolated supervised fatwa-system bridge."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.fatwa import (
    FatwaBridgeRequest,
    FatwaBridgeResult,
    FatwaBridgeStatus,
    FatwaResultOutcome,
)
from app.persistence.repositories import EventNotFound
from app.persistence.sqlite import SQLiteDatabase

_MAX_BRIDGE_NAME = 80
_MAX_EXTERNAL_ID = 256
_MAX_APPROVER = 128
_MAX_SOURCE_REF = 512
_MAX_ANSWER_TEXT = 16000


class FatwaBridgeConflict(RuntimeError):
    """Raised when request/dispatch idempotency evidence conflicts."""


class FatwaResultConflict(RuntimeError):
    """Raised when an external result key/request is reused with different semantics."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _from_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _bounded(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    return normalized


def _compact(value: str, *, field: str, maximum: int) -> str:
    normalized = _bounded(value, field=field, maximum=maximum)
    if any(char.isspace() for char in normalized):
        raise ValueError(f"{field} must be a compact identifier")
    return normalized


def _request_from_row(row: sqlite3.Row) -> FatwaBridgeRequest:
    return FatwaBridgeRequest(
        id=str(row["id"]),
        event_id=str(row["event_id"]),
        classification_result_id=str(row["classification_result_id"]),
        status=FatwaBridgeStatus(str(row["status"])),
        dispatch_attempt_count=int(row["dispatch_attempt_count"]),
        bridge_name=str(row["bridge_name"]) if row["bridge_name"] is not None else None,
        external_case_id=(
            str(row["external_case_id"])
            if row["external_case_id"] is not None
            else None
        ),
        created_at=_from_timestamp(str(row["created_at"])),
        updated_at=_from_timestamp(str(row["updated_at"])),
    )


def _result_from_row(row: sqlite3.Row) -> FatwaBridgeResult:
    return FatwaBridgeResult(
        id=str(row["id"]),
        request_id=str(row["request_id"]),
        external_result_key=str(row["external_result_key"]),
        outcome=FatwaResultOutcome(str(row["outcome"])),
        answer_text=str(row["answer_text"]) if row["answer_text"] is not None else None,
        approved_by=str(row["approved_by"]) if row["approved_by"] is not None else None,
        source_ref=str(row["source_ref"]),
        received_at=_from_timestamp(str(row["received_at"])),
    )


class FatwaRepository:
    """Durable idempotency and lifecycle boundary for supervised fatwa routing."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get_for_event(self, event_id: str) -> FatwaBridgeRequest | None:
        """Return the durable bridge request for an event, if present."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM fatwa_bridge_requests WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return _request_from_row(row) if row is not None else None

    def get_request(self, request_id: str) -> FatwaBridgeRequest:
        """Load one bridge request by internal id."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM fatwa_bridge_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            raise LookupError(request_id)
        return _request_from_row(row)

    def count_requests(self) -> int:
        """Return bridge request count."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM fatwa_bridge_requests"
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def create_request(
        self,
        *,
        event_id: str,
        classification_result_id: str,
    ) -> FatwaBridgeRequest:
        """Create exactly one bridge request for an authoritative FATWA result."""

        request_id = str(uuid4())
        now = _utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            event_exists = connection.execute(
                "SELECT 1 FROM inbound_events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if event_exists is None:
                connection.rollback()
                raise EventNotFound(event_id)

            classification = connection.execute(
                "SELECT event_id, route FROM classification_results WHERE id = ?",
                (classification_result_id,),
            ).fetchone()
            if (
                classification is None
                or str(classification["event_id"]) != event_id
                or str(classification["route"]) != "FATWA"
            ):
                connection.rollback()
                raise ValueError("classification is not eligible for FATWA bridge")

            try:
                connection.execute(
                    """
                    INSERT INTO fatwa_bridge_requests (
                        id, event_id, classification_result_id, status,
                        dispatch_attempt_count, bridge_name, external_case_id,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request_id,
                        event_id,
                        classification_result_id,
                        FatwaBridgeStatus.PENDING_DISPATCH.value,
                        0,
                        None,
                        None,
                        _to_timestamp(now),
                        _to_timestamp(now),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM fatwa_bridge_requests WHERE id = ?",
                    (request_id,),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise RuntimeError("inserted fatwa bridge request could not be reloaded")
                return _request_from_row(row)
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM fatwa_bridge_requests WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise
                existing = _request_from_row(row)
                if existing.classification_result_id != classification_result_id:
                    raise FatwaBridgeConflict(
                        "event is already bound to different FATWA classification evidence"
                    ) from None
                return existing

    def record_dispatch_failure(self, request_id: str) -> FatwaBridgeRequest:
        """Increment an attempt counter without persisting raw transport errors."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fatwa_bridge_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise LookupError(request_id)
            request = _request_from_row(row)
            if request.status is not FatwaBridgeStatus.PENDING_DISPATCH:
                connection.rollback()
                raise ValueError("only pending FATWA requests may record dispatch failure")
            now = _utc_now()
            connection.execute(
                """
                UPDATE fatwa_bridge_requests
                SET dispatch_attempt_count = dispatch_attempt_count + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (_to_timestamp(now), request_id),
            )
            updated = connection.execute(
                "SELECT * FROM fatwa_bridge_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            connection.commit()
        if updated is None:
            raise RuntimeError("fatwa dispatch failure state could not be reloaded")
        return _request_from_row(updated)

    def mark_dispatched(
        self,
        request_id: str,
        *,
        bridge_name: str,
        external_case_id: str,
    ) -> FatwaBridgeRequest:
        """Record successful dispatch and transition to awaiting_result."""

        bridge = _compact(bridge_name, field="bridge_name", maximum=_MAX_BRIDGE_NAME)
        case_id = _compact(
            external_case_id,
            field="external_case_id",
            maximum=_MAX_EXTERNAL_ID,
        )
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fatwa_bridge_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise LookupError(request_id)
            current = _request_from_row(row)
            if current.status in {
                FatwaBridgeStatus.AWAITING_RESULT,
                FatwaBridgeStatus.APPROVED_RESULT,
                FatwaBridgeStatus.REJECTED,
            }:
                connection.commit()
                if current.bridge_name == bridge and current.external_case_id == case_id:
                    return current
                raise FatwaBridgeConflict(
                    "fatwa request is already bound to different dispatch evidence"
                )
            if current.status is FatwaBridgeStatus.CANCELLED:
                connection.rollback()
                raise ValueError("cancelled FATWA request cannot be dispatched")

            now = _utc_now()
            try:
                connection.execute(
                    """
                    UPDATE fatwa_bridge_requests
                    SET status = ?, dispatch_attempt_count = dispatch_attempt_count + 1,
                        bridge_name = ?, external_case_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        FatwaBridgeStatus.AWAITING_RESULT.value,
                        bridge,
                        case_id,
                        _to_timestamp(now),
                        request_id,
                    ),
                )
                updated = connection.execute(
                    "SELECT * FROM fatwa_bridge_requests WHERE id = ?",
                    (request_id,),
                ).fetchone()
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise FatwaBridgeConflict(
                    "external_case_id is already bound to another FATWA request"
                ) from exc
        if updated is None:
            raise RuntimeError("dispatched fatwa request could not be reloaded")
        return _request_from_row(updated)

    def cancel(self, request_id: str) -> FatwaBridgeRequest:
        """Cancel a request only before a terminal external result exists."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fatwa_bridge_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise LookupError(request_id)
            current = _request_from_row(row)
            if current.status in {
                FatwaBridgeStatus.APPROVED_RESULT,
                FatwaBridgeStatus.REJECTED,
                FatwaBridgeStatus.CANCELLED,
            }:
                connection.rollback()
                raise ValueError("terminal FATWA request cannot be cancelled")
            now = _utc_now()
            connection.execute(
                "UPDATE fatwa_bridge_requests SET status = ?, updated_at = ? WHERE id = ?",
                (FatwaBridgeStatus.CANCELLED.value, _to_timestamp(now), request_id),
            )
            updated = connection.execute(
                "SELECT * FROM fatwa_bridge_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            connection.commit()
        if updated is None:
            raise RuntimeError("cancelled fatwa request could not be reloaded")
        return _request_from_row(updated)

    def get_result(self, request_id: str) -> FatwaBridgeResult | None:
        """Return the accepted external result for a request, if present."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM fatwa_bridge_results WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        return _result_from_row(row) if row is not None else None

    def accept_result(
        self,
        request_id: str,
        *,
        external_result_key: str,
        outcome: FatwaResultOutcome,
        answer_text: str | None,
        approved_by: str | None,
        source_ref: str,
        received_at: datetime,
    ) -> FatwaBridgeResult:
        """Accept one attributed external result and atomically close the request."""

        result_key = _compact(
            external_result_key,
            field="external_result_key",
            maximum=_MAX_EXTERNAL_ID,
        )
        source = _bounded(source_ref, field="source_ref", maximum=_MAX_SOURCE_REF)
        received_timestamp = _to_timestamp(received_at)

        if outcome is FatwaResultOutcome.APPROVED:
            if answer_text is None or approved_by is None:
                raise ValueError("approved FATWA result requires answer_text and approved_by")
            answer = _bounded(
                answer_text,
                field="answer_text",
                maximum=_MAX_ANSWER_TEXT,
            )
            approver = _bounded(
                approved_by,
                field="approved_by",
                maximum=_MAX_APPROVER,
            )
        else:
            if answer_text is not None or approved_by is not None:
                raise ValueError("rejected FATWA result must not contain answer or approver")
            answer = None
            approver = None

        result_id = str(uuid4())
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            request_row = connection.execute(
                "SELECT * FROM fatwa_bridge_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if request_row is None:
                connection.rollback()
                raise LookupError(request_id)

            existing_row = connection.execute(
                """
                SELECT * FROM fatwa_bridge_results
                WHERE request_id = ? OR external_result_key = ?
                LIMIT 1
                """,
                (request_id, result_key),
            ).fetchone()
            if existing_row is not None:
                connection.commit()
                existing = _result_from_row(existing_row)
                if (
                    existing.request_id == request_id
                    and existing.external_result_key == result_key
                    and existing.outcome is outcome
                    and existing.answer_text == answer
                    and existing.approved_by == approver
                    and existing.source_ref == source
                ):
                    return existing
                raise FatwaResultConflict(
                    "FATWA result key or request is already bound differently"
                )

            request = _request_from_row(request_row)
            if request.status is not FatwaBridgeStatus.AWAITING_RESULT:
                connection.rollback()
                raise ValueError("FATWA result requires awaiting_result state")

            terminal_status = (
                FatwaBridgeStatus.APPROVED_RESULT
                if outcome is FatwaResultOutcome.APPROVED
                else FatwaBridgeStatus.REJECTED
            )
            try:
                connection.execute(
                    """
                    INSERT INTO fatwa_bridge_results (
                        id, request_id, external_result_key, outcome,
                        answer_text, approved_by, source_ref, received_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result_id,
                        request_id,
                        result_key,
                        outcome.value,
                        answer,
                        approver,
                        source,
                        received_timestamp,
                    ),
                )
                now = _utc_now()
                connection.execute(
                    "UPDATE fatwa_bridge_requests SET status = ?, updated_at = ? WHERE id = ?",
                    (terminal_status.value, _to_timestamp(now), request_id),
                )
                created = connection.execute(
                    "SELECT * FROM fatwa_bridge_results WHERE id = ?",
                    (result_id,),
                ).fetchone()
                connection.commit()
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT * FROM fatwa_bridge_results
                    WHERE request_id = ? OR external_result_key = ?
                    LIMIT 1
                    """,
                    (request_id, result_key),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise
                existing = _result_from_row(row)
                if (
                    existing.request_id == request_id
                    and existing.external_result_key == result_key
                    and existing.outcome is outcome
                    and existing.answer_text == answer
                    and existing.approved_by == approver
                    and existing.source_ref == source
                ):
                    return existing
                raise FatwaResultConflict(
                    "concurrent FATWA result conflicts with accepted result"
                ) from None

        if created is None:
            raise RuntimeError("accepted fatwa result could not be reloaded")
        return _result_from_row(created)
