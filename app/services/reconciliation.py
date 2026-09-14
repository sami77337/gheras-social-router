"""Operator-facing service for provider-verified publication reconciliation."""

from __future__ import annotations

from app.domain.events import OutboundAction
from app.domain.reconciliation import (
    PublicationReconciliationDecision,
    PublicationReconciliationRecord,
)
from app.persistence.reconciliation_repository import PublicationReconciliationRepository


class PublicationReconciliationService:
    """Expose only explicit verified outcomes; never infer or auto-retry publication."""

    def __init__(self, repository: PublicationReconciliationRepository) -> None:
        self.repository = repository

    def confirm_succeeded(
        self,
        *,
        action_id: str,
        operator_ref: str,
        evidence_ref: str,
        external_reconciliation_key: str,
        external_result_id: str,
    ) -> tuple[PublicationReconciliationRecord, OutboundAction]:
        """Record provider-confirmed success and close the held action as succeeded."""

        return self.repository.reconcile(
            action_id=action_id,
            decision=PublicationReconciliationDecision.CONFIRMED_SUCCEEDED,
            operator_ref=operator_ref,
            evidence_ref=evidence_ref,
            external_reconciliation_key=external_reconciliation_key,
            external_result_id=external_result_id,
        )

    def confirm_not_sent(
        self,
        *,
        action_id: str,
        operator_ref: str,
        evidence_ref: str,
        external_reconciliation_key: str,
    ) -> tuple[PublicationReconciliationRecord, OutboundAction]:
        """Record verified non-delivery and return the action to pending for later dispatch."""

        return self.repository.reconcile(
            action_id=action_id,
            decision=PublicationReconciliationDecision.CONFIRMED_NOT_SENT,
            operator_ref=operator_ref,
            evidence_ref=evidence_ref,
            external_reconciliation_key=external_reconciliation_key,
        )
