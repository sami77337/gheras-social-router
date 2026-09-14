"""SQLite repository for human-supervisor escalations and accepted responses."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.supervisor import (
    SupervisorEscalation,
    SupervisorEscalationSource,
    SupervisorEscalationStatus,
    SupervisorResponse,
)
from app.persistence.repositories import EventNotFound
from app.persistence.sqlite import SQLiteDatabase

_MAX_TRANSPORT_NAME = 80
_MAX_EXTERNAL_ID = 256
_MAX_SUPERVISOR_REF = 128
_MAX_RESPONSE_TEXT = 8000


class SupervisorEscalationConflict(RuntimeError):
    """Raised when one event is bound to contradictory escalation evidence."""


class SupervisorResponseConflict(RuntimeError):
    """Raised when response idempotency semantics conflict."""


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


def _escalation_from_row(row: sqlite3.Row) -> SupervisorEscalation:
    source = SupervisorEscalationSource(str(row["source"]))
    source_result_id = (
        str(row["classification_result_id"])
        if source is SupervisorEscalationSource.CLASSIFICATION
        else str(row["faq_resolution_id"])
    )
    return SupervisorEscalation(
        id=str(row["id"]),
        event_id=str(row["event_id"]),
        source=source,
        source_result_id=source_result_id,
        status=SupervisorEscalationStatus(str(row["status"])),
        dispatch_attempt_count=int(row["dispatch_attempt_count"]),
        external_thread_id=(
            str(row["external_thread_id"])
            if row["external_thread_id"] is not None
            else None
        ),
        created_at=_from_timestamp(str(row["created_at"])),
        updated_at=_from_timestamp(str(row["updated_at"])),
    )


def _response_from_row(row: sqlite3.Row) -> SupervisorResponse:
    return SupervisorResponse(
        id=str(row["id"]),
        escalation_id=str(row["escalation_id"]),
        external_response_key=str(row["external_response_key"]),
        supervisor_ref=str(row["supervisor_ref"]),
        text=str(row["response_text"]),
        received_at=_from_timestamp(str(row["received_at"])),
    )


class SupervisorRepository:
    """Durable state boundary for human escalation workflow."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get_for_event(self, event_id: str) -> SupervisorEscalation | None:
        """Return one escalation for an event, if it exists."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM supervisor_escalations WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return _escalation_from_row(row) if row is not None else None

    def count_escalations(self) -> int:
        """Return the number of durable escalations."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM supervisor_escalations"
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def create_from_classification(
        self,
        *,
        event_id: str,
        classification_result_id: str,
    ) -> SupervisorEscalation:
        """Create an escalation for an explicit SUPERVISOR classification."""

        return self._create(
            event_id=event_id,
            source=SupervisorEscalationSource.CLASSIFICATION,
            source_result_id=classification_result_id,
        )

    def create_from_faq_resolution(
        self,
        *,
        event_id: str,
        faq_resolution_id: str,
    ) -> SupervisorEscalation:
        """Create an escalation for a supervisor-required FAQ resolution."""

        return self._create(
            event_id=event_id,
            source=SupervisorEscalationSource.FAQ_RESOLUTION,
            source_result_id=faq_resolution_id,
        )

    def _create(
        self,
        *,
        event_id: str,
        source: SupervisorEscalationSource,
        source_result_id: str,
    ) -> SupervisorEscalation:
        escalation_id = str(uuid4())
        now = _utc_now()
        classification_id: str | None = None
        faq_resolution_id: str | None = None

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            event_exists = connection.execute(
                "SELECT 1 FROM inbound_events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if event_exists is None:
                connection.rollback()
                raise EventNotFound(event_id)

            if source is SupervisorEscalationSource.CLASSIFICATION:
                evidence = connection.execute(
                    "SELECT event_id, route FROM classification_results WHERE id = ?",
                    (source_result_id,),
                ).fetchone()
                if (
                    evidence is None
                    or str(evidence["event_id"]) != event_id
                    or str(evidence["route"]) != "SUPERVISOR"
                ):
                    connection.rollback()
                    raise ValueError("classification is not eligible for supervisor escalation")
                classification_id = source_result_id
            else:
                evidence = connection.execute(
                    "SELECT event_id, status FROM faq_resolutions WHERE id = ?",
                    (source_result_id,),
                ).fetchone()
                if (
                    evidence is None
                    or str(evidence["event_id"]) != event_id
                    or str(evidence["status"]) != "supervisor_required"
                ):
                    connection.rollback()
                    raise ValueError("FAQ resolution is not eligible for supervisor escalation")
                faq_resolution_id = source_result_id

            try:
                connection.execute(
                    """
                    INSERT INTO supervisor_escalations (
                        id, event_id, source, classification_result_id,
                        faq_resolution_id, status, dispatch_attempt_count,
                        transport_name, external_thread_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        escalation_id,
                        event_id,
                        source.value,
                        classification_id,
                        faq_resolution_id,
                        SupervisorEscalationStatus.PENDING_DISPATCH.value,
                        0,
                        None,
                        None,
                        _to_timestamp(now),
                        _to_timestamp(now),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM supervisor_escalations WHERE id = ?",
                    (escalation_id,),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise RuntimeError("inserted supervisor escalation could not be reloaded")
                return _escalation_from_row(row)
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM supervisor_escalations WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise
                existing = _escalation_from_row(row)
                if existing.source is not source or existing.source_result_id != source_result_id:
                    raise SupervisorEscalationConflict(
                        "event is already bound to different supervisor evidence"
                    ) from None
                return existing

    def record_dispatch_failure(self, escalation_id: str) -> SupervisorEscalation:
        """Record one failed transport attempt without persisting exception text."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM supervisor_escalations WHERE id = ?",
                (escalation_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise LookupError(escalation_id)
            current = _escalation_from_row(row)
            if current.status is not SupervisorEscalationStatus.PENDING_DISPATCH:
                connection.rollback()
                raise ValueError("only pending escalations may record dispatch failure")
            now = _utc_now()
            connection.execute(
                """
                UPDATE supervisor_escalations
                SET dispatch_attempt_count = dispatch_attempt_count + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (_to_timestamp(now), escalation_id),
            )
            updated = connection.execute(
                "SELECT * FROM supervisor_escalations WHERE id = ?",
                (escalation_id,),
            ).fetchone()
            connection.commit()
        if updated is None:
            raise RuntimeError("dispatch failure state could not be reloaded")
        return _escalation_from_row(updated)

    def mark_dispatched(
        self,
        escalation_id: str,
        *,
        transport_name: str,
        external_thread_id: str,
    ) -> SupervisorEscalation:
        """Record successful transport dispatch and await a human response."""

        transport = _compact(
            transport_name,
            field="transport_name",
            maximum=_MAX_TRANSPORT_NAME,
        )
        thread_id = _compact(
            external_thread_id,
            field="external_thread_id",
            maximum=_MAX_EXTERNAL_ID,
        )
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM supervisor_escalations WHERE id = ?",
                (escalation_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise LookupError(escalation_id)
            current = _escalation_from_row(row)
            stored_transport = row["transport_name"]
            stored_thread = row["external_thread_id"]
            if current.status in {
                SupervisorEscalationStatus.AWAITING_RESPONSE,
                SupervisorEscalationStatus.RESPONDED,
            }:
                connection.commit()
                if str(stored_transport) == transport and str(stored_thread) == thread_id:
                    return current
                raise SupervisorEscalationConflict(
                    "escalation is already bound to different transport evidence"
                )
            if current.status is not SupervisorEscalationStatus.PENDING_DISPATCH:
                connection.rollback()
                raise ValueError("cancelled escalation cannot be dispatched")
            now = _utc_now()
            try:
                connection.execute(
                    """
                    UPDATE supervisor_escalations
                    SET status = ?, dispatch_attempt_count = dispatch_attempt_count + 1,
                        transport_name = ?, external_thread_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        SupervisorEscalationStatus.AWAITING_RESPONSE.value,
                        transport,
                        thread_id,
                        _to_timestamp(now),
                        escalation_id,
                    ),
                )
                updated = connection.execute(
                    "SELECT * FROM supervisor_escalations WHERE id = ?",
                    (escalation_id,),
                ).fetchone()
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise SupervisorEscalationConflict(
                    "external_thread_id is already bound to another escalation"
                ) from exc
        if updated is None:
            raise RuntimeError("dispatched escalation could not be reloaded")
        return _escalation_from_row(updated)

    def cancel(self, escalation_id: str) -> SupervisorEscalation:
        """Cancel a pending or awaiting escalation through an explicit local action."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM supervisor_escalations WHERE id = ?",
                (escalation_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise LookupError(escalation_id)
            current = _escalation_from_row(row)
            if current.status in {
                SupervisorEscalationStatus.RESPONDED,
                SupervisorEscalationStatus.CANCELLED,
            }:
                connection.rollback()
                raise ValueError("responded or cancelled escalation cannot be cancelled")
            now = _utc_now()
            connection.execute(
                "UPDATE supervisor_escalations SET status = ?, updated_at = ? WHERE id = ?",
                (
                    SupervisorEscalationStatus.CANCELLED.value,
                    _to_timestamp(now),
                    escalation_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM supervisor_escalations WHERE id = ?",
                (escalation_id,),
            ).fetchone()
            connection.commit()
        if updated is None:
            raise RuntimeError("cancelled escalation could not be reloaded")
        return _escalation_from_row(updated)

    def get_response(self, escalation_id: str) -> SupervisorResponse | None:
        """Return the accepted response for an escalation, if one exists."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM supervisor_responses WHERE escalation_id = ?",
                (escalation_id,),
            ).fetchone()
        return _response_from_row(row) if row is not None else None

    def accept_response(
        self,
        escalation_id: str,
        *,
        external_response_key: str,
        supervisor_ref: str,
        text: str,
        received_at: datetime,
    ) -> SupervisorResponse:
        """Accept exactly one idempotent human response for an awaiting escalation."""

        response_key = _compact(
            external_response_key,
            field="external_response_key",
            maximum=_MAX_EXTERNAL_ID,
        )
        supervisor = _compact(
            supervisor_ref,
            field="supervisor_ref",
            maximum=_MAX_SUPERVISOR_REF,
        )
        response_text = _bounded(text, field="text", maximum=_MAX_RESPONSE_TEXT)
        received_timestamp = _to_timestamp(received_at)
        response_id = str(uuid4())

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            escalation_row = connection.execute(
                "SELECT * FROM supervisor_escalations WHERE id = ?",
                (escalation_id,),
            ).fetchone()
            if escalation_row is None:
                connection.rollback()
                raise LookupError(escalation_id)

            existing_row = connection.execute(
                """
                SELECT * FROM supervisor_responses
                WHERE escalation_id = ? OR external_response_key = ?
                LIMIT 1
                """,
                (escalation_id, response_key),
            ).fetchone()
            if existing_row is not None:
                connection.commit()
                existing = _response_from_row(existing_row)
                if (
                    existing.escalation_id == escalation_id
                    and existing.external_response_key == response_key
                    and existing.supervisor_ref == supervisor
                    and existing.text == response_text
                ):
                    return existing
                raise SupervisorResponseConflict(
                    "response idempotency key or escalation is already bound differently"
                )

            escalation = _escalation_from_row(escalation_row)
            if escalation.status is not SupervisorEscalationStatus.AWAITING_RESPONSE:
                connection.rollback()
                raise ValueError("supervisor response requires awaiting_response state")

            try:
                connection.execute(
                    """
                    INSERT INTO supervisor_responses (
                        id, escalation_id, external_response_key,
                        supervisor_ref, response_text, received_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        response_id,
                        escalation_id,
                        response_key,
                        supervisor,
                        response_text,
                        received_timestamp,
                    ),
                )
                now = _utc_now()
                connection.execute(
                    "UPDATE supervisor_escalations SET status = ?, updated_at = ? WHERE id = ?",
                    (
                        SupervisorEscalationStatus.RESPONDED.value,
                        _to_timestamp(now),
                        escalation_id,
                    ),
                )
                created = connection.execute(
                    "SELECT * FROM supervisor_responses WHERE id = ?",
                    (response_id,),
                ).fetchone()
                connection.commit()
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT * FROM supervisor_responses
                    WHERE escalation_id = ? OR external_response_key = ?
                    LIMIT 1
                    """,
                    (escalation_id, response_key),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise
                existing = _response_from_row(row)
                if (
                    existing.escalation_id == escalation_id
                    and existing.external_response_key == response_key
                    and existing.supervisor_ref == supervisor
                    and existing.text == response_text
                ):
                    return existing
                raise SupervisorResponseConflict(
                    "concurrent response conflicts with accepted response"
                ) from None

        if created is None:
            raise RuntimeError("accepted supervisor response could not be reloaded")
        return _response_from_row(created)
