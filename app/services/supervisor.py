"""Durable supervisor escalation orchestration without live transport side effects."""

from __future__ import annotations

from datetime import datetime

from app.domain.classification import ClassificationRoute
from app.domain.faq import FAQResolutionStatus
from app.domain.supervisor import (
    SupervisorDispatchRequest,
    SupervisorEscalation,
    SupervisorEscalationSource,
    SupervisorEscalationStatus,
    SupervisorResponse,
)
from app.persistence.classification_repository import ClassificationRepository
from app.persistence.faq_repository import FAQRepository
from app.persistence.repositories import DurableRepository
from app.persistence.supervisor_repository import SupervisorRepository


class SupervisorNotEligible(RuntimeError):
    """Raised when an event has no durable evidence requiring human supervision."""


class SupervisorDispatchNotReady(RuntimeError):
    """Raised when dispatch preparation is requested from an invalid lifecycle state."""


class SupervisorService:
    """Create and advance human escalation state while transport remains external."""

    def __init__(
        self,
        *,
        events: DurableRepository,
        classifications: ClassificationRepository,
        faqs: FAQRepository,
        supervisors: SupervisorRepository,
    ) -> None:
        self.events = events
        self.classifications = classifications
        self.faqs = faqs
        self.supervisors = supervisors

    def ensure_escalation(self, event_id: str) -> SupervisorEscalation:
        """Create or return the single durable escalation justified by routing evidence."""

        existing = self.supervisors.get_for_event(event_id)
        if existing is not None:
            return existing

        classification = self.classifications.get_for_event(event_id)
        if classification is None:
            raise SupervisorNotEligible("supervisor escalation requires classification evidence")

        if classification.route is ClassificationRoute.SUPERVISOR:
            return self.supervisors.create_from_classification(
                event_id=event_id,
                classification_result_id=classification.id,
            )

        if classification.route is ClassificationRoute.FAQ:
            resolution = self.faqs.get_resolution(event_id)
            if (
                resolution is not None
                and resolution.status is FAQResolutionStatus.SUPERVISOR_REQUIRED
            ):
                return self.supervisors.create_from_faq_resolution(
                    event_id=event_id,
                    faq_resolution_id=resolution.id,
                )

        raise SupervisorNotEligible(
            "event is neither SUPERVISOR-routed nor supervisor-required FAQ"
        )

    def prepare_dispatch(self, event_id: str) -> SupervisorDispatchRequest:
        """Build the minimal transport payload without performing an external call."""

        escalation = self.ensure_escalation(event_id)
        if escalation.status is not SupervisorEscalationStatus.PENDING_DISPATCH:
            raise SupervisorDispatchNotReady(
                "only pending_dispatch escalation may produce a dispatch request"
            )
        event = self.events.get_event(event_id)
        return SupervisorDispatchRequest(
            escalation_id=escalation.id,
            event_id=event.id,
            platform=event.platform.value,
            text=event.text,
            correlation_id=event.correlation_id,
        )

    def record_dispatch_failure(self, event_id: str) -> SupervisorEscalation:
        """Increment durable attempt metadata without storing raw transport errors."""

        escalation = self.ensure_escalation(event_id)
        return self.supervisors.record_dispatch_failure(escalation.id)

    def mark_dispatched(
        self,
        event_id: str,
        *,
        transport_name: str,
        external_thread_id: str,
    ) -> SupervisorEscalation:
        """Record transport success after an adapter returns a stable external id."""

        escalation = self.ensure_escalation(event_id)
        return self.supervisors.mark_dispatched(
            escalation.id,
            transport_name=transport_name,
            external_thread_id=external_thread_id,
        )

    def accept_response(
        self,
        event_id: str,
        *,
        external_response_key: str,
        supervisor_ref: str,
        text: str,
        received_at: datetime,
    ) -> SupervisorResponse:
        """Accept one normalized human response for a dispatched escalation."""

        escalation = self.ensure_escalation(event_id)
        return self.supervisors.accept_response(
            escalation.id,
            external_response_key=external_response_key,
            supervisor_ref=supervisor_ref,
            text=text,
            received_at=received_at,
        )

    def source_for_event(self, event_id: str) -> SupervisorEscalationSource | None:
        """Expose escalation evidence type for audit/reporting without provider payloads."""

        escalation = self.supervisors.get_for_event(event_id)
        return escalation.source if escalation is not None else None
