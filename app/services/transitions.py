"""State transition service for durable inbound events."""

from __future__ import annotations

from app.domain.events import InboundEvent
from app.domain.states import ProcessingState
from app.persistence.repositories import DurableRepository


class TransitionService:
    """Coordinate explicit persisted event-state transitions."""

    def __init__(self, repository: DurableRepository) -> None:
        self.repository = repository

    def transition(self, event_id: str, target: ProcessingState) -> InboundEvent:
        """Validate and persist one domain transition."""

        return self.repository.transition_event(event_id, target)
