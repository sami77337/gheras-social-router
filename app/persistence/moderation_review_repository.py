"""SQLite persistence for human moderation review and resume evidence."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.moderation import ModerationDisposition
from app.domain.moderation_review import (
    ModerationHumanDecision,
    ModerationHumanReview,
    ModerationHumanReviewStatus,
)
from app.persistence.repositories import EventNotFound
from app.persistence.sqlite import SQLiteDatabase

_MAX_REVIEWER_REF = 128
_MAX_EXTERNAL_REVIEW_KEY = 256


class ModerationReviewConflict(RuntimeError):
    """Raised when durable human-review evidence is reused inconsistently."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _from_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _compact(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    if any(char.isspace() for char in normalized):
        raise ValueError(f"{field} must be a compact identifier")
    return normalized


def _review_from_row(row: sqlite3.Row) -> ModerationHumanReview:
    decision_raw = row["decision"]
    resolved_at_raw = row["resolved_at"]
    return ModerationHumanReview(
        id=str(row["id"]),
        event_id=str(row["event_id"]),
        moderation_result_id=str(row["moderation_result_id"]),
        status=ModerationHumanReviewStatus(str(row["status"])),
        decision=(
            ModerationHumanDecision(str(decision_raw))
            if decision_raw is not None
            else None
        ),
        reviewer_ref=(str(row["reviewer_ref"]) if row["reviewer_ref"] is not None else None),
        external_review_key=(
            str(row["external_review_key"])
            if row["external_review_key"] is not None
            else None
        ),
        created_at=_from_timestamp(str(row["created_at"])),
        resolved_at=(
            _from_timestamp(str(resolved_at_raw)) if resolved_at_raw is not None else None
        ),
    )


class ModerationReviewRepository:
    """Durable review evidence layered over immutable machine moderation results."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get_for_event(self, event_id: str) -> ModerationHumanReview | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM moderation_human_reviews WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return _review_from_row(row) if row is not None else None

    def count_reviews(self) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM moderation_human_reviews"
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def ensure_pending(
        self,
        *,
        event_id: str,
        moderation_result_id: str,
    ) -> ModerationHumanReview:
        """Create exactly one pending review for a HUMAN_REVIEW moderation result."""

        review_id = str(uuid4())
        created_at = _utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            event = connection.execute(
                "SELECT 1 FROM inbound_events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if event is None:
                connection.rollback()
                raise EventNotFound(event_id)

            moderation = connection.execute(
                "SELECT event_id, disposition FROM moderation_results WHERE id = ?",
                (moderation_result_id,),
            ).fetchone()
            if (
                moderation is None
                or str(moderation["event_id"]) != event_id
                or str(moderation["disposition"])
                != ModerationDisposition.HUMAN_REVIEW.value
            ):
                connection.rollback()
                raise ValueError("moderation result is not eligible for human review")

            existing = connection.execute(
                "SELECT * FROM moderation_human_reviews WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if existing is not None:
                connection.commit()
                review = _review_from_row(existing)
                if review.moderation_result_id != moderation_result_id:
                    raise ModerationReviewConflict(
                        "event is already bound to different moderation review evidence"
                    )
                return review

            connection.execute(
                """
                INSERT INTO moderation_human_reviews (
                    id, event_id, moderation_result_id, status, decision,
                    reviewer_ref, external_review_key, created_at, resolved_at
                ) VALUES (?, ?, ?, 'pending', NULL, NULL, NULL, ?, NULL)
                """,
                (review_id, event_id, moderation_result_id, _to_timestamp(created_at)),
            )
            row = connection.execute(
                "SELECT * FROM moderation_human_reviews WHERE id = ?",
                (review_id,),
            ).fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError("inserted moderation review could not be reloaded")
        return _review_from_row(row)

    def resolve(
        self,
        *,
        event_id: str,
        decision: ModerationHumanDecision,
        reviewer_ref: str,
        external_review_key: str,
    ) -> ModerationHumanReview:
        """Resolve one pending review exactly once with idempotent human evidence."""

        safe_reviewer = _compact(
            reviewer_ref,
            field="reviewer_ref",
            maximum=_MAX_REVIEWER_REF,
        )
        safe_external_key = _compact(
            external_review_key,
            field="external_review_key",
            maximum=_MAX_EXTERNAL_REVIEW_KEY,
        )
        resolved_at = _utc_now()

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM moderation_human_reviews WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise LookupError("moderation human review does not exist")

            existing = _review_from_row(row)
            if existing.status is ModerationHumanReviewStatus.RESOLVED:
                connection.commit()
                if (
                    existing.decision is decision
                    and existing.reviewer_ref == safe_reviewer
                    and existing.external_review_key == safe_external_key
                ):
                    return existing
                raise ModerationReviewConflict(
                    "moderation human review is already resolved with different evidence"
                )

            key_owner = connection.execute(
                """
                SELECT event_id FROM moderation_human_reviews
                WHERE external_review_key = ?
                """,
                (safe_external_key,),
            ).fetchone()
            if key_owner is not None and str(key_owner["event_id"]) != event_id:
                connection.rollback()
                raise ModerationReviewConflict(
                    "external_review_key is already bound to another event"
                )

            connection.execute(
                """
                UPDATE moderation_human_reviews
                SET status = 'resolved', decision = ?, reviewer_ref = ?,
                    external_review_key = ?, resolved_at = ?
                WHERE event_id = ? AND status = 'pending'
                """,
                (
                    decision.value,
                    safe_reviewer,
                    safe_external_key,
                    _to_timestamp(resolved_at),
                    event_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM moderation_human_reviews WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError("resolved moderation review could not be reloaded")
        return _review_from_row(row)
