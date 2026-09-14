"""Durable, idempotent persistence for side-effect-free shadow evaluations."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.classification import ClassificationRoute
from app.domain.events import Platform
from app.domain.publishing import PublicationSourceKind
from app.domain.shadow import ShadowDecision, ShadowEvaluation, ShadowOutcome, ShadowSummary
from app.persistence.repositories import EventNotFound
from app.persistence.sqlite import SQLiteDatabase


class ShadowConflict(RuntimeError):
    """Raised when an event/version key is reused for different shadow semantics."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _from_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _evaluation_from_row(row: sqlite3.Row) -> ShadowEvaluation:
    route = row["observed_route"]
    source_kind = row["source_kind"]
    return ShadowEvaluation(
        id=str(row["id"]),
        event_id=str(row["event_id"]),
        correlation_id=str(row["correlation_id"]),
        platform=Platform(str(row["platform"])),
        evaluator_version=str(row["evaluator_version"]),
        observed_route=(ClassificationRoute(str(route)) if route is not None else None),
        outcome=ShadowOutcome(str(row["outcome"])),
        source_kind=(
            PublicationSourceKind(str(source_kind)) if source_kind is not None else None
        ),
        evidence_id=(str(row["evidence_id"]) if row["evidence_id"] is not None else None),
        proposed_text=(
            str(row["proposed_text"]) if row["proposed_text"] is not None else None
        ),
        created_at=_from_timestamp(str(row["created_at"])),
    )


def _matches(existing: ShadowEvaluation, decision: ShadowDecision) -> bool:
    return (
        existing.event_id == decision.event_id
        and existing.correlation_id == decision.correlation_id
        and existing.platform is decision.platform
        and existing.evaluator_version == decision.evaluator_version.strip()
        and existing.observed_route is decision.observed_route
        and existing.outcome is decision.outcome
        and existing.source_kind is decision.source_kind
        and existing.evidence_id == decision.evidence_id
        and existing.proposed_text == decision.proposed_text
    )


class ShadowRepository:
    """Store one immutable evaluation per event and evaluator version."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get(self, event_id: str, evaluator_version: str) -> ShadowEvaluation | None:
        """Return one previously persisted evaluation."""

        version = evaluator_version.strip()
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM shadow_evaluations
                WHERE event_id = ? AND evaluator_version = ?
                """,
                (event_id, version),
            ).fetchone()
        return _evaluation_from_row(row) if row is not None else None

    def record(self, decision: ShadowDecision) -> ShadowEvaluation:
        """Persist a shadow decision or return the identical winner of a duplicate race."""

        evaluation_id = str(uuid4())
        version = decision.evaluator_version.strip()
        now = _utc_now()

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            event = connection.execute(
                "SELECT platform, correlation_id FROM inbound_events WHERE id = ?",
                (decision.event_id,),
            ).fetchone()
            if event is None:
                connection.rollback()
                raise EventNotFound(decision.event_id)
            if (
                str(event["platform"]) != decision.platform.value
                or str(event["correlation_id"]) != decision.correlation_id
            ):
                connection.rollback()
                raise ValueError("shadow decision identity does not match durable event")

            try:
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
                        decision.event_id,
                        decision.correlation_id,
                        decision.platform.value,
                        version,
                        (
                            decision.observed_route.value
                            if decision.observed_route is not None
                            else None
                        ),
                        decision.outcome.value,
                        (
                            decision.source_kind.value
                            if decision.source_kind is not None
                            else None
                        ),
                        decision.evidence_id,
                        decision.proposed_text,
                        _to_timestamp(now),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM shadow_evaluations WHERE id = ?",
                    (evaluation_id,),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise RuntimeError("inserted shadow evaluation could not be reloaded")
                return _evaluation_from_row(row)
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT * FROM shadow_evaluations
                    WHERE event_id = ? AND evaluator_version = ?
                    """,
                    (decision.event_id, version),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise
                existing = _evaluation_from_row(row)
                if not _matches(existing, decision):
                    raise ShadowConflict(
                        "event/evaluator version is already bound to different evidence"
                    ) from None
                return existing

    def count(self) -> int:
        """Return the number of persisted shadow evaluations."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM shadow_evaluations"
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def summary(self) -> ShadowSummary:
        """Return aggregate metrics without exposing proposed reply text."""

        with self.database.connect() as connection:
            total_row = connection.execute(
                "SELECT COUNT(*) AS count FROM shadow_evaluations"
            ).fetchone()
            platform_rows = connection.execute(
                """
                SELECT platform, COUNT(*) AS count
                FROM shadow_evaluations GROUP BY platform ORDER BY platform
                """
            ).fetchall()
            route_rows = connection.execute(
                """
                SELECT observed_route, COUNT(*) AS count
                FROM shadow_evaluations GROUP BY observed_route ORDER BY observed_route
                """
            ).fetchall()
            outcome_rows = connection.execute(
                """
                SELECT outcome, COUNT(*) AS count
                FROM shadow_evaluations GROUP BY outcome ORDER BY outcome
                """
            ).fetchall()
            publish_row = connection.execute(
                """
                SELECT COUNT(*) AS count FROM shadow_evaluations
                WHERE outcome = 'would_publish'
                """
            ).fetchone()

        total = int(total_row["count"]) if total_row is not None else 0
        publishable = int(publish_row["count"]) if publish_row is not None else 0
        by_platform = {str(row["platform"]): int(row["count"]) for row in platform_rows}
        by_route = {
            (str(row["observed_route"]) if row["observed_route"] is not None else "none"):
            int(row["count"])
            for row in route_rows
        }
        by_outcome = {str(row["outcome"]): int(row["count"]) for row in outcome_rows}
        return ShadowSummary(
            total_evaluated=total,
            by_platform=by_platform,
            by_route=by_route,
            by_outcome=by_outcome,
            publishable=publishable,
            non_publishable=total - publishable,
        )
