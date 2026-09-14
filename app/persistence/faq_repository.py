"""SQLite repository for approved FAQ versions and durable resolutions."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.faq import (
    FAQEntry,
    FAQEntryStatus,
    FAQResolution,
    FAQResolutionReason,
    FAQResolutionStatus,
)
from app.persistence.repositories import EventNotFound
from app.persistence.sqlite import SQLiteDatabase

_MAX_FAQ_KEY_LENGTH = 128
_MAX_APPROVER_LENGTH = 128
_MAX_SOURCE_REF_LENGTH = 512


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _from_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _compact_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_FAQ_KEY_LENGTH:
        raise ValueError("faq_key must be a compact identifier of at most 128 characters")
    if any(char.isspace() for char in normalized):
        raise ValueError("faq_key must not contain whitespace")
    return normalized


def _bounded_text(value: str, *, field: str, maximum: int | None = None) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if maximum is not None and len(normalized) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    return normalized


def _entry_from_row(row: sqlite3.Row) -> FAQEntry:
    return FAQEntry(
        id=str(row["id"]),
        faq_key=str(row["faq_key"]),
        version=int(row["version"]),
        answer_text=str(row["answer_text"]),
        source_ref=str(row["source_ref"]),
        status=FAQEntryStatus(str(row["status"])),
        approved_by=str(row["approved_by"]),
        approved_at=_from_timestamp(str(row["approved_at"])),
        created_at=_from_timestamp(str(row["created_at"])),
    )


def _resolution_from_row(row: sqlite3.Row) -> FAQResolution:
    entry_id = row["faq_entry_id"]
    return FAQResolution(
        id=str(row["id"]),
        event_id=str(row["event_id"]),
        classification_result_id=str(row["classification_result_id"]),
        faq_entry_id=str(entry_id) if entry_id is not None else None,
        status=FAQResolutionStatus(str(row["status"])),
        reason=FAQResolutionReason(str(row["reason_code"])),
        created_at=_from_timestamp(str(row["created_at"])),
    )


class FAQRepository:
    """Store immutable FAQ content versions and one durable resolution per event."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def create_version(
        self,
        *,
        faq_key: str,
        answer_text: str,
        source_ref: str,
        approved_by: str,
        approved_at: datetime,
        activate: bool = True,
    ) -> FAQEntry:
        """Append a FAQ version; never rewrite historical answer/provenance content."""

        key = _compact_key(faq_key)
        answer = _bounded_text(answer_text, field="answer_text")
        source = _bounded_text(source_ref, field="source_ref", maximum=_MAX_SOURCE_REF_LENGTH)
        approver = _bounded_text(
            approved_by,
            field="approved_by",
            maximum=_MAX_APPROVER_LENGTH,
        )
        approved_timestamp = _to_timestamp(approved_at)
        now = _utc_now()
        entry_id = str(uuid4())

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next_version "
                "FROM faq_entries WHERE faq_key = ?",
                (key,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise RuntimeError("could not allocate FAQ version")
            version = int(row["next_version"])

            if activate:
                connection.execute(
                    "UPDATE faq_entries SET status = 'disabled' "
                    "WHERE faq_key = ? AND status = 'active'",
                    (key,),
                )

            connection.execute(
                """
                INSERT INTO faq_entries (
                    id, faq_key, version, answer_text, source_ref, status,
                    approved_by, approved_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    key,
                    version,
                    answer,
                    source,
                    FAQEntryStatus.ACTIVE.value if activate else FAQEntryStatus.DISABLED.value,
                    approver,
                    approved_timestamp,
                    _to_timestamp(now),
                ),
            )
            created = connection.execute(
                "SELECT * FROM faq_entries WHERE id = ?",
                (entry_id,),
            ).fetchone()
            connection.commit()

        if created is None:
            raise RuntimeError("inserted FAQ entry could not be reloaded")
        return _entry_from_row(created)

    def disable_active(self, faq_key: str) -> FAQEntry | None:
        """Disable the currently active version without deleting historical evidence."""

        key = _compact_key(faq_key)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM faq_entries WHERE faq_key = ? AND status = 'active'",
                (key,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                "UPDATE faq_entries SET status = 'disabled' WHERE id = ?",
                (str(row["id"]),),
            )
            updated = connection.execute(
                "SELECT * FROM faq_entries WHERE id = ?",
                (str(row["id"]),),
            ).fetchone()
            connection.commit()
        if updated is None:
            raise RuntimeError("disabled FAQ entry could not be reloaded")
        return _entry_from_row(updated)

    def get_active(self, faq_key: str) -> FAQEntry | None:
        """Return the exact active FAQ entry; no fuzzy or substitute lookup."""

        key = _compact_key(faq_key)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM faq_entries WHERE faq_key = ? AND status = 'active'",
                (key,),
            ).fetchone()
        return _entry_from_row(row) if row is not None else None

    def get_entry(self, entry_id: str) -> FAQEntry:
        """Load one immutable FAQ version by internal identifier."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM faq_entries WHERE id = ?",
                (entry_id,),
            ).fetchone()
        if row is None:
            raise LookupError(entry_id)
        return _entry_from_row(row)

    def has_versions(self, faq_key: str) -> bool:
        """Return whether any exact historical version exists for this key."""

        key = _compact_key(faq_key)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM faq_entries WHERE faq_key = ? LIMIT 1",
                (key,),
            ).fetchone()
        return row is not None

    def list_versions(self, faq_key: str) -> tuple[FAQEntry, ...]:
        """Return exact-key versions in ascending version order."""

        key = _compact_key(faq_key)
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM faq_entries WHERE faq_key = ? ORDER BY version ASC",
                (key,),
            ).fetchall()
        return tuple(_entry_from_row(row) for row in rows)

    def count_entries(self) -> int:
        """Return FAQ-entry count; a fresh database must have zero production seeds."""

        with self.database.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM faq_entries").fetchone()
        return int(row["count"]) if row is not None else 0

    def get_resolution(self, event_id: str) -> FAQResolution | None:
        """Return the durable FAQ resolution for an event, if present."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM faq_resolutions WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return _resolution_from_row(row) if row is not None else None

    def count_resolutions(self) -> int:
        """Return FAQ-resolution count."""

        with self.database.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM faq_resolutions").fetchone()
        return int(row["count"]) if row is not None else 0

    def create_resolution(
        self,
        *,
        event_id: str,
        classification_result_id: str,
        status: FAQResolutionStatus,
        reason: FAQResolutionReason,
        faq_entry_id: str | None,
    ) -> FAQResolution:
        """Persist one resolution per event and return the winner of duplicate races."""

        if status is FAQResolutionStatus.RESOLVED:
            if reason is not FAQResolutionReason.APPROVED_ENTRY or faq_entry_id is None:
                raise ValueError("resolved FAQ requires exact approved entry evidence")
        elif reason is FAQResolutionReason.APPROVED_ENTRY or faq_entry_id is not None:
            raise ValueError("supervisor-required FAQ resolution cannot carry an approved entry")

        resolution_id = str(uuid4())
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
                "SELECT event_id FROM classification_results WHERE id = ?",
                (classification_result_id,),
            ).fetchone()
            if classification is None or str(classification["event_id"]) != event_id:
                connection.rollback()
                raise ValueError("classification result does not belong to event")
            if faq_entry_id is not None:
                entry = connection.execute(
                    "SELECT status FROM faq_entries WHERE id = ?",
                    (faq_entry_id,),
                ).fetchone()
                if entry is None or str(entry["status"]) != FAQEntryStatus.ACTIVE.value:
                    connection.rollback()
                    raise ValueError("resolved FAQ entry must still be active")

            try:
                connection.execute(
                    """
                    INSERT INTO faq_resolutions (
                        id, event_id, classification_result_id, faq_entry_id,
                        status, reason_code, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resolution_id,
                        event_id,
                        classification_result_id,
                        faq_entry_id,
                        status.value,
                        reason.value,
                        _to_timestamp(now),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM faq_resolutions WHERE id = ?",
                    (resolution_id,),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise RuntimeError("inserted FAQ resolution could not be reloaded")
                return _resolution_from_row(row)
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM faq_resolutions WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise
                return _resolution_from_row(row)
