"""Domain records for explicit operator reconciliation of uncertain publication outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.publishing import PublicationStatus


class PublicationReconciliationDecision(StrEnum):
    """Only provider-verified outcomes an operator may record."""

    CONFIRMED_SUCCEEDED = "confirmed_succeeded"
    CONFIRMED_NOT_SENT = "confirmed_not_sent"


@dataclass(frozen=True, slots=True)
class PublicationReconciliationRecord:
    """Immutable evidence for one manual publication reconciliation decision."""

    id: str
    action_id: str
    prior_status: PublicationStatus
    decision: PublicationReconciliationDecision
    operator_ref: str
    evidence_ref: str
    external_reconciliation_key: str
    external_result_id: str | None
    created_at: datetime
