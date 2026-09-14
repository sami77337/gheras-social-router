"""Domain models for durable human-supervisor escalation and response handling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SupervisorEscalationStatus(StrEnum):
    """Lifecycle for one durable human escalation."""

    PENDING_DISPATCH = "pending_dispatch"
    AWAITING_RESPONSE = "awaiting_response"
    RESPONDED = "responded"
    CANCELLED = "cancelled"


class SupervisorEscalationSource(StrEnum):
    """Evidence source that made an event eligible for supervisor handling."""

    CLASSIFICATION = "classification"
    FAQ_RESOLUTION = "faq_resolution"


@dataclass(frozen=True, slots=True)
class SupervisorEscalation:
    """One durable escalation linked to exact routing evidence."""

    id: str
    event_id: str
    source: SupervisorEscalationSource
    source_result_id: str
    status: SupervisorEscalationStatus
    dispatch_attempt_count: int
    external_thread_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SupervisorResponse:
    """One accepted human response for an escalation."""

    id: str
    escalation_id: str
    external_response_key: str
    supervisor_ref: str
    text: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class SupervisorDispatchRequest:
    """Minimal provider-neutral payload required to notify a supervisor."""

    escalation_id: str
    event_id: str
    platform: str
    text: str | None
    correlation_id: str
