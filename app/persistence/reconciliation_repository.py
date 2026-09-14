"""Atomic persistence for explicit publication reconciliation decisions."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.events import OutboundAction, Platform
from app.domain.publishing import PublicationStatus
from app.domain.reconciliation import (
    PublicationReconciliationDecision,
    PublicationReconciliationRecord,
)
from app.persistence.repositories import IdempotencyConflict
from app.persistence.sqlite import SQLiteDatabase


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _from_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _required_text(value: str, *, field: str, maximum: int = 512) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds maximum length")
    return normalized


def _compact_identifier(value: str, *, field: str, maximum: int = 512) -> str:
    normalized = _required_text(value, field=field, maximum=maximum)
    if any(char.isspace() for char in normalized):
        raise ValueError(f"{field} must be a compact identifier")
    return normalized


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


def _record_from_row(row: sqlite3.Row) -> PublicationReconciliationRecord:
    return PublicationReconciliationRecord(
        id=str(row["id"]),
        action_id=str(row["action_id"]),
        prior_status=PublicationStatus(str(row["prior_status"])),
        decision=PublicationReconciliationDecision(str(row["decision"])),
        operator_ref=str(row["operator_ref"]),
        evidence_ref=str(row["evidence_ref"]),
        external_reconciliation_key=str(row["external_reconciliation_key"]),
        external_result_id=(
            str(row["external_result_id"])
            if row["external_result_id"] is not None
            else None
        ),
        created_at=_from_timestamp(str(row["created_at"])),
    )


class PublicationReconciliationRepository:
    """Resolve publication holds only from explicit provider-verified evidence."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def reconcile(
        self,
        *,
        action_id: str,
        decision: PublicationReconciliationDecision,
        operator_ref: str,
        evidence_ref: str,
        external_reconciliation_key: str,
        external_result_id: str | None = None,
    ) -> tuple[PublicationReconciliationRecord, OutboundAction]:
        """Record evidence and atomically move one held action to its verified state."""

        safe_operator = _required_text(operator_ref, field="operator_ref")
        safe_evidence = _required_text(evidence_ref, field="evidence_ref")
        safe_key = _compact_identifier(
            external_reconciliation_key,
            field="external_reconciliation_key",
            maximum=256,
        )
        safe_result: str | None = None
        if decision is PublicationReconciliationDecision.CONFIRMED_SUCCEEDED:
            if external_result_id is None:
                raise ValueError("confirmed_succeeded requires external_result_id")
            safe_result = _compact_identifier(
                external_result_id,
                field="external_result_id",
            )
        elif external_result_id is not None:
            raise ValueError("confirmed_not_sent must not include external_result_id")

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_row = connection.execute(
                """
                SELECT * FROM publication_reconciliations
                WHERE external_reconciliation_key = ?
                """,
                (safe_key,),
            ).fetchone()
            if existing_row is not None:
                existing = _record_from_row(existing_row)
                if (
                    existing.action_id != action_id
                    or existing.decision is not decision
                    or existing.operator_ref != safe_operator
                    or existing.evidence_ref != safe_evidence
                    or existing.external_result_id != safe_result
                ):
                    connection.rollback()
                    raise IdempotencyConflict(
                        "reconciliation key is already bound to different semantics"
                    )
                action_row = connection.execute(
                    "SELECT * FROM outbound_actions WHERE id = ?",
                    (action_id,),
                ).fetchone()
                connection.commit()
                if action_row is None:
                    raise RuntimeError("reconciled outbound action could not be reloaded")
                return existing, _action_from_row(action_row)

            action_row = connection.execute(
                "SELECT * FROM outbound_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
            if action_row is None:
                connection.rollback()
                raise LookupError(action_id)
            action = _action_from_row(action_row)
            prior_status = PublicationStatus(action.status)
            if prior_status not in {
                PublicationStatus.DISPATCHING,
                PublicationStatus.UNCERTAIN,
            }:
                connection.rollback()
                raise ValueError("only dispatching or uncertain publication may be reconciled")

            record_id = str(uuid4())
            now = _utc_now()
            connection.execute(
                """
                INSERT INTO publication_reconciliations (
                    id, action_id, prior_status, decision, operator_ref,
                    evidence_ref, external_reconciliation_key,
                    external_result_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    action_id,
                    prior_status.value,
                    decision.value,
                    safe_operator,
                    safe_evidence,
                    safe_key,
                    safe_result,
                    _to_timestamp(now),
                ),
            )

            if decision is PublicationReconciliationDecision.CONFIRMED_SUCCEEDED:
                next_status = PublicationStatus.SUCCEEDED
            else:
                next_status = PublicationStatus.PENDING
            connection.execute(
                """
                UPDATE outbound_actions
                SET status = ?, external_result_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    next_status.value,
                    safe_result,
                    _to_timestamp(now),
                    action_id,
                ),
            )
            record_row = connection.execute(
                "SELECT * FROM publication_reconciliations WHERE id = ?",
                (record_id,),
            ).fetchone()
            updated_action_row = connection.execute(
                "SELECT * FROM outbound_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
            connection.commit()

        if record_row is None or updated_action_row is None:
            raise RuntimeError("reconciliation transaction could not be reloaded")
        return _record_from_row(record_row), _action_from_row(updated_action_row)
