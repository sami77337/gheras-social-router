from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.publishing import PublicationStatus
from app.domain.reconciliation import PublicationReconciliationDecision
from app.persistence.reconciliation_repository import PublicationReconciliationRepository
from app.persistence.repositories import IdempotencyConflict
from app.persistence.sqlite import SQLiteDatabase
from app.services.reconciliation import PublicationReconciliationService


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _setup_action(
    tmp_path: Path,
    *,
    status: PublicationStatus,
) -> tuple[SQLiteDatabase, str]:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()
    now = _timestamp()
    event_id = "event-1"
    action_id = "action-1"
    with database.connect() as connection:
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
                "facebook",
                "event-key-1",
                "external-event-1",
                "comment-1",
                "post-1",
                "author-1",
                "sensitive body",
                None,
                "correlation-1",
                "received",
                0,
                None,
                now,
                now,
            ),
        )
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
                "facebook",
                "reply:faq:evidence-1",
                "publish-key-1",
                status.value,
                None,
                now,
                now,
            ),
        )
    return database, action_id


def test_confirmed_success_closes_uncertain_action(tmp_path: Path) -> None:
    database, action_id = _setup_action(tmp_path, status=PublicationStatus.UNCERTAIN)
    service = PublicationReconciliationService(PublicationReconciliationRepository(database))

    record, action = service.confirm_succeeded(
        action_id=action_id,
        operator_ref="operator-7",
        evidence_ref="provider-case-42",
        external_reconciliation_key="reconcile-1",
        external_result_id="provider-result-99",
    )

    assert record.prior_status is PublicationStatus.UNCERTAIN
    assert record.decision is PublicationReconciliationDecision.CONFIRMED_SUCCEEDED
    assert action.status == PublicationStatus.SUCCEEDED.value
    assert action.external_result_id == "provider-result-99"


def test_confirmed_not_sent_returns_dispatching_action_to_pending(tmp_path: Path) -> None:
    database, action_id = _setup_action(tmp_path, status=PublicationStatus.DISPATCHING)
    service = PublicationReconciliationService(PublicationReconciliationRepository(database))

    record, action = service.confirm_not_sent(
        action_id=action_id,
        operator_ref="operator-7",
        evidence_ref="provider-search-no-match",
        external_reconciliation_key="reconcile-2",
    )

    assert record.prior_status is PublicationStatus.DISPATCHING
    assert record.decision is PublicationReconciliationDecision.CONFIRMED_NOT_SENT
    assert action.status == PublicationStatus.PENDING.value
    assert action.external_result_id is None


def test_reconciliation_is_idempotent_for_same_external_key(tmp_path: Path) -> None:
    database, action_id = _setup_action(tmp_path, status=PublicationStatus.UNCERTAIN)
    service = PublicationReconciliationService(PublicationReconciliationRepository(database))
    arguments = {
        "action_id": action_id,
        "operator_ref": "operator-7",
        "evidence_ref": "provider-case-42",
        "external_reconciliation_key": "reconcile-3",
        "external_result_id": "provider-result-100",
    }

    first_record, first_action = service.confirm_succeeded(**arguments)
    second_record, second_action = service.confirm_succeeded(**arguments)

    assert second_record == first_record
    assert second_action == first_action


def test_reconciliation_key_conflict_is_rejected(tmp_path: Path) -> None:
    database, action_id = _setup_action(tmp_path, status=PublicationStatus.UNCERTAIN)
    service = PublicationReconciliationService(PublicationReconciliationRepository(database))
    service.confirm_succeeded(
        action_id=action_id,
        operator_ref="operator-7",
        evidence_ref="provider-case-42",
        external_reconciliation_key="reconcile-4",
        external_result_id="provider-result-101",
    )

    with pytest.raises(IdempotencyConflict):
        service.confirm_succeeded(
            action_id=action_id,
            operator_ref="operator-8",
            evidence_ref="different-evidence",
            external_reconciliation_key="reconcile-4",
            external_result_id="provider-result-102",
        )


def test_pending_or_succeeded_actions_cannot_be_reconciled(tmp_path: Path) -> None:
    database, action_id = _setup_action(tmp_path, status=PublicationStatus.PENDING)
    service = PublicationReconciliationService(PublicationReconciliationRepository(database))

    with pytest.raises(ValueError, match="dispatching or uncertain"):
        service.confirm_not_sent(
            action_id=action_id,
            operator_ref="operator-7",
            evidence_ref="provider-no-match",
            external_reconciliation_key="reconcile-5",
        )


def test_confirmed_success_requires_provider_result_id(tmp_path: Path) -> None:
    database, action_id = _setup_action(tmp_path, status=PublicationStatus.UNCERTAIN)
    repository = PublicationReconciliationRepository(database)

    with pytest.raises(ValueError, match="requires external_result_id"):
        repository.reconcile(
            action_id=action_id,
            decision=PublicationReconciliationDecision.CONFIRMED_SUCCEEDED,
            operator_ref="operator-7",
            evidence_ref="provider-case-42",
            external_reconciliation_key="reconcile-6",
        )
