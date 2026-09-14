"""Durable FATWA bridge orchestration with no religious answer generation."""

from __future__ import annotations

from datetime import datetime

from app.domain.classification import ClassificationRoute
from app.domain.fatwa import (
    FatwaBridgeDispatch,
    FatwaBridgeRequest,
    FatwaBridgeResult,
    FatwaBridgeStatus,
    FatwaResultOutcome,
)
from app.persistence.classification_repository import ClassificationRepository
from app.persistence.fatwa_repository import FatwaRepository
from app.persistence.repositories import DurableRepository


class FatwaNotEligible(RuntimeError):
    """Raised when an event has no authoritative FATWA classification."""


class FatwaDispatchNotReady(RuntimeError):
    """Raised when dispatch preparation is requested from a non-pending request."""


class FatwaService:
    """Route FATWA events to an external supervised system without generating answers."""

    def __init__(
        self,
        *,
        events: DurableRepository,
        classifications: ClassificationRepository,
        fatwas: FatwaRepository,
    ) -> None:
        self.events = events
        self.classifications = classifications
        self.fatwas = fatwas

    def ensure_request(self, event_id: str) -> FatwaBridgeRequest:
        """Create or return the one request justified by a durable FATWA route."""

        existing = self.fatwas.get_for_event(event_id)
        if existing is not None:
            return existing
        classification = self.classifications.get_for_event(event_id)
        if classification is None or classification.route is not ClassificationRoute.FATWA:
            raise FatwaNotEligible("fatwa bridge requires a durable FATWA classification")
        return self.fatwas.create_request(
            event_id=event_id,
            classification_result_id=classification.id,
        )

    def prepare_dispatch(self, event_id: str) -> FatwaBridgeDispatch:
        """Return the minimal external bridge payload without performing a live call."""

        request = self.ensure_request(event_id)
        if request.status is not FatwaBridgeStatus.PENDING_DISPATCH:
            raise FatwaDispatchNotReady(
                "only pending_dispatch FATWA request may produce dispatch payload"
            )
        event = self.events.get_event(event_id)
        return FatwaBridgeDispatch(
            request_id=request.id,
            event_id=event.id,
            platform=event.platform.value,
            question_text=event.text,
            correlation_id=event.correlation_id,
        )

    def record_dispatch_failure(self, event_id: str) -> FatwaBridgeRequest:
        """Record an unsuccessful bridge attempt without raw diagnostics."""

        request = self.ensure_request(event_id)
        return self.fatwas.record_dispatch_failure(request.id)

    def mark_dispatched(
        self,
        event_id: str,
        *,
        bridge_name: str,
        external_case_id: str,
    ) -> FatwaBridgeRequest:
        """Record successful handoff to the external supervised fatwa system."""

        request = self.ensure_request(event_id)
        return self.fatwas.mark_dispatched(
            request.id,
            bridge_name=bridge_name,
            external_case_id=external_case_id,
        )

    def accept_result(
        self,
        event_id: str,
        *,
        external_result_key: str,
        outcome: FatwaResultOutcome,
        answer_text: str | None,
        approved_by: str | None,
        source_ref: str,
        received_at: datetime,
    ) -> FatwaBridgeResult:
        """Accept only normalized external supervised result evidence."""

        request = self.ensure_request(event_id)
        return self.fatwas.accept_result(
            request.id,
            external_result_key=external_result_key,
            outcome=outcome,
            answer_text=answer_text,
            approved_by=approved_by,
            source_ref=source_ref,
            received_at=received_at,
        )

    def get_publishable_answer(self, event_id: str) -> str | None:
        """Expose exact external answer text only after a fully approved terminal result."""

        request = self.fatwas.get_for_event(event_id)
        if request is None or request.status is not FatwaBridgeStatus.APPROVED_RESULT:
            return None
        result = self.fatwas.get_result(request.id)
        if result is None:
            raise RuntimeError("approved FATWA request is missing its external result")
        return result.publishable_answer
