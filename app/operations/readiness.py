"""Content-free operational readiness and reconciliation visibility."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from app.domain.events import Platform
from app.domain.publishing import PublicationStatus
from app.operations.database import DatabaseIntegrityReport, inspect_database
from app.persistence.sqlite import SQLiteDatabase


@dataclass(frozen=True, slots=True)
class OperationalSnapshot:
    """Counts-only operational state suitable for health/readiness surfaces."""

    integrity: DatabaseIntegrityReport
    inbound_total: int
    inbound_received: int
    inbound_processing: int
    inbound_waiting_human: int
    inbound_failed_retryable: int
    inbound_failed_terminal: int
    pending_moderation_reviews: int
    supervisor_pending_dispatch: int
    supervisor_awaiting_response: int
    fatwa_pending_dispatch: int
    fatwa_awaiting_result: int
    publications_pending: int
    publications_dispatching: int
    publications_uncertain: int
    publications_succeeded: int
    shadow_total: int

    @property
    def requires_operator_attention(self) -> bool:
        return bool(
            not self.integrity.acceptable
            or self.publications_dispatching
            or self.publications_uncertain
            or self.inbound_failed_terminal
        )


@dataclass(frozen=True, slots=True)
class PublicationReconciliationItem:
    """Opaque publication hold requiring operator/provider-side reconciliation."""

    action_id: str
    platform: Platform
    status: PublicationStatus
    updated_at: datetime


class OperationalReadinessService:
    """Read-only operational queries; this service never retries or mutates work."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    @staticmethod
    def _count(
        connection: sqlite3.Connection,
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> int:
        row = connection.execute(query, parameters).fetchone()
        return int(row[0]) if row is not None else 0

    def snapshot(self) -> OperationalSnapshot:
        """Return counts and integrity only; no inbound/reply text is selected."""

        integrity = inspect_database(self.database)
        with self.database.connect_readonly() as connection:
            count = self._count
            return OperationalSnapshot(
                integrity=integrity,
                inbound_total=count(connection, "SELECT COUNT(*) FROM inbound_events"),
                inbound_received=count(
                    connection,
                    "SELECT COUNT(*) FROM inbound_events WHERE status = ?",
                    ("received",),
                ),
                inbound_processing=count(
                    connection,
                    "SELECT COUNT(*) FROM inbound_events WHERE status = ?",
                    ("processing",),
                ),
                inbound_waiting_human=count(
                    connection,
                    "SELECT COUNT(*) FROM inbound_events WHERE status = ?",
                    ("waiting_human",),
                ),
                inbound_failed_retryable=count(
                    connection,
                    "SELECT COUNT(*) FROM inbound_events WHERE status = ?",
                    ("failed_retryable",),
                ),
                inbound_failed_terminal=count(
                    connection,
                    "SELECT COUNT(*) FROM inbound_events WHERE status = ?",
                    ("failed_terminal",),
                ),
                pending_moderation_reviews=count(
                    connection,
                    "SELECT COUNT(*) FROM moderation_human_reviews WHERE status = ?",
                    ("pending",),
                ),
                supervisor_pending_dispatch=count(
                    connection,
                    "SELECT COUNT(*) FROM supervisor_escalations WHERE status = ?",
                    ("pending_dispatch",),
                ),
                supervisor_awaiting_response=count(
                    connection,
                    "SELECT COUNT(*) FROM supervisor_escalations WHERE status = ?",
                    ("awaiting_response",),
                ),
                fatwa_pending_dispatch=count(
                    connection,
                    "SELECT COUNT(*) FROM fatwa_bridge_requests WHERE status = ?",
                    ("pending_dispatch",),
                ),
                fatwa_awaiting_result=count(
                    connection,
                    "SELECT COUNT(*) FROM fatwa_bridge_requests WHERE status = ?",
                    ("awaiting_result",),
                ),
                publications_pending=count(
                    connection,
                    "SELECT COUNT(*) FROM outbound_actions WHERE status = ?",
                    (PublicationStatus.PENDING.value,),
                ),
                publications_dispatching=count(
                    connection,
                    "SELECT COUNT(*) FROM outbound_actions WHERE status = ?",
                    (PublicationStatus.DISPATCHING.value,),
                ),
                publications_uncertain=count(
                    connection,
                    "SELECT COUNT(*) FROM outbound_actions WHERE status = ?",
                    (PublicationStatus.UNCERTAIN.value,),
                ),
                publications_succeeded=count(
                    connection,
                    "SELECT COUNT(*) FROM outbound_actions WHERE status = ?",
                    (PublicationStatus.SUCCEEDED.value,),
                ),
                shadow_total=count(connection, "SELECT COUNT(*) FROM shadow_evaluations"),
            )

    def publication_reconciliation_items(self) -> tuple[PublicationReconciliationItem, ...]:
        """List only opaque publication holds; never retry or expose source/reply text."""

        with self.database.connect_readonly() as connection:
            rows = connection.execute(
                """
                SELECT id, platform, status, updated_at
                FROM outbound_actions
                WHERE status IN (?, ?)
                ORDER BY updated_at, id
                """,
                (
                    PublicationStatus.DISPATCHING.value,
                    PublicationStatus.UNCERTAIN.value,
                ),
            ).fetchall()
        return tuple(
            PublicationReconciliationItem(
                action_id=str(row["id"]),
                platform=Platform(str(row["platform"])),
                status=PublicationStatus(str(row["status"])),
                updated_at=datetime.fromisoformat(str(row["updated_at"])),
            )
            for row in rows
        )
