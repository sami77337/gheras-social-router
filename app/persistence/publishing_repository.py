"""Atomic lifecycle operations for the durable outbound publication ledger."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.events import OutboundAction, Platform
from app.domain.publishing import PublicationStatus, PublishableContent
from app.persistence.repositories import EventNotFound, IdempotencyConflict
from app.persistence.sqlite import SQLiteDatabase


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _from_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _action_from_row(row: sqlite3.Row) -> OutboundAction:
    return OutboundAction(
        id=str(row["id"]),
        event_id=str(row["event_id"]),
        platform=Platform(str(row["platform"])),
        action_type=str(row["action_type"]),
        idempotency_key=str(row["idempotency_key"]),
        status=str(row["status"]),
        external_result_id=(
            str(row["external_result_id"])
            if row["external_result_id"] is not None
            else None
        ),
        created_at=_from_timestamp(str(row["created_at"])),
        updated_at=_from_timestamp(str(row["updated_at"])),
    )


def _action_type(content: PublishableContent) -> str:
    return f"reply:{content.source_kind.value}:{content.evidence_id}"


def _idempotency_key(content: PublishableContent) -> str:
    return (
        f"publish:{content.event_id}:{content.platform.value}:"
        f"{content.source_kind.value}:{content.evidence_id}"
    )


class PublishingRepository:
    """Persist and atomically claim one exact-source publication intent."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def ensure_action(self, content: PublishableContent) -> OutboundAction:
        """Create the durable intent before any external publisher is called."""

        action_id = str(uuid4())
        action_type = _action_type(content)
        idempotency_key = _idempotency_key(content)
        now = _utc_now()

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            event = connection.execute(
                "SELECT platform FROM inbound_events WHERE id = ?",
                (content.event_id,),
            ).fetchone()
            if event is None:
                connection.rollback()
                raise EventNotFound(content.event_id)
            if str(event["platform"]) != content.platform.value:
                connection.rollback()
                raise ValueError("publication platform does not match inbound event")

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
                        content.event_id,
                        content.platform.value,
                        action_type,
                        idempotency_key,
                        PublicationStatus.PENDING.value,
                        None,
                        _to_timestamp(now),
                        _to_timestamp(now),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM outbound_actions WHERE id = ?",
                    (action_id,),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise RuntimeError("inserted outbound action could not be reloaded")
                return _action_from_row(row)
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
                    existing.event_id != content.event_id
                    or existing.platform is not content.platform
                    or existing.action_type != action_type
                ):
                    raise IdempotencyConflict(
                        "publication key is already bound to different semantics"
                    ) from None
                return existing

    def claim(self, action_id: str) -> tuple[OutboundAction, bool]:
        """Atomically move one pending action to dispatching for exactly one worker."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM outbound_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise LookupError(action_id)
            current = _action_from_row(row)
            status = PublicationStatus(current.status)
            if status is not PublicationStatus.PENDING:
                connection.commit()
                return current, False

            now = _utc_now()
            connection.execute(
                "UPDATE outbound_actions SET status = ?, updated_at = ? WHERE id = ?",
                (PublicationStatus.DISPATCHING.value, _to_timestamp(now), action_id),
            )
            updated = connection.execute(
                "SELECT * FROM outbound_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
            connection.commit()
        if updated is None:
            raise RuntimeError("claimed outbound action could not be reloaded")
        return _action_from_row(updated), True

    def mark_succeeded(self, action_id: str, external_result_id: str) -> OutboundAction:
        """Record a stable provider result after a claimed external call succeeds."""

        result_id = external_result_id.strip()
        if not result_id or any(char.isspace() for char in result_id):
            raise ValueError("external_result_id must be a compact identifier")
        if len(result_id) > 512:
            raise ValueError("external_result_id exceeds maximum identifier length")

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM outbound_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise LookupError(action_id)
            current = _action_from_row(row)
            status = PublicationStatus(current.status)
            if status is PublicationStatus.SUCCEEDED:
                connection.commit()
                if current.external_result_id == result_id:
                    return current
                raise IdempotencyConflict(
                    "succeeded publication is bound to a different provider result"
                )
            if status is not PublicationStatus.DISPATCHING:
                connection.rollback()
                raise ValueError("only dispatching action may become succeeded")

            now = _utc_now()
            connection.execute(
                """
                UPDATE outbound_actions
                SET status = ?, external_result_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    PublicationStatus.SUCCEEDED.value,
                    result_id,
                    _to_timestamp(now),
                    action_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM outbound_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
            connection.commit()
        if updated is None:
            raise RuntimeError("succeeded outbound action could not be reloaded")
        return _action_from_row(updated)

    def mark_uncertain(self, action_id: str) -> OutboundAction:
        """Freeze a started attempt whose external side-effect outcome is unknown."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM outbound_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise LookupError(action_id)
            current = _action_from_row(row)
            status = PublicationStatus(current.status)
            if status is PublicationStatus.UNCERTAIN:
                connection.commit()
                return current
            if status is not PublicationStatus.DISPATCHING:
                connection.rollback()
                raise ValueError("only dispatching action may become uncertain")

            now = _utc_now()
            connection.execute(
                "UPDATE outbound_actions SET status = ?, updated_at = ? WHERE id = ?",
                (PublicationStatus.UNCERTAIN.value, _to_timestamp(now), action_id),
            )
            updated = connection.execute(
                "SELECT * FROM outbound_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
            connection.commit()
        if updated is None:
            raise RuntimeError("uncertain outbound action could not be reloaded")
        return _action_from_row(updated)

    def count_actions(self) -> int:
        """Return current outbound action count."""

        with self.database.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM outbound_actions").fetchone()
        return int(row["count"]) if row is not None else 0
