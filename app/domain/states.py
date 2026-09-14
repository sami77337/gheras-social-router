"""Processing state machine for durable inbound events."""

from __future__ import annotations

from enum import StrEnum


class ProcessingState(StrEnum):
    """Durable lifecycle states for an accepted inbound event."""

    RECEIVED = "received"
    PROCESSING = "processing"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


ALLOWED_TRANSITIONS: dict[ProcessingState, frozenset[ProcessingState]] = {
    ProcessingState.RECEIVED: frozenset({ProcessingState.PROCESSING}),
    ProcessingState.PROCESSING: frozenset(
        {
            ProcessingState.COMPLETED,
            ProcessingState.WAITING_HUMAN,
            ProcessingState.FAILED_RETRYABLE,
            ProcessingState.FAILED_TERMINAL,
        }
    ),
    ProcessingState.WAITING_HUMAN: frozenset(
        {ProcessingState.PROCESSING, ProcessingState.COMPLETED}
    ),
    ProcessingState.FAILED_RETRYABLE: frozenset({ProcessingState.PROCESSING}),
    ProcessingState.COMPLETED: frozenset(),
    ProcessingState.FAILED_TERMINAL: frozenset(),
}


class InvalidStateTransition(ValueError):
    """Raised when a requested event-state transition is not allowed."""

    def __init__(self, current: ProcessingState, target: ProcessingState) -> None:
        self.current = current
        self.target = target
        super().__init__(f"invalid transition: {current.value} -> {target.value}")


def validate_transition(current: ProcessingState, target: ProcessingState) -> None:
    """Validate an explicit transition according to the Phase 1 state machine."""

    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransition(current, target)
