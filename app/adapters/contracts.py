"""Protocol boundaries for future external integrations."""

from __future__ import annotations

from typing import Protocol

from app.domain.classification import ClassificationAssessment, ClassificationRequest
from app.domain.fatwa import FatwaBridgeDispatch
from app.domain.moderation import ModerationAssessment, ModerationRequest
from app.domain.supervisor import SupervisorDispatchRequest


class InboundCollector(Protocol):
    """Contract for a platform that can collect or receive inbound comments."""

    async def start(self) -> None:
        """Start receiving inbound events."""
        ...


class ReplyPublisher(Protocol):
    """Contract for publishing a reply to an originating platform."""

    async def publish_reply(self, *, external_comment_id: str, text: str) -> str:
        """Publish a reply and return the platform reply identifier."""
        ...


class ModerationAdapter(Protocol):
    """Provider-neutral async boundary for text/media moderation evidence."""

    @property
    def name(self) -> str:
        """Stable adapter identifier suitable for audit persistence."""
        ...

    @property
    def version(self) -> str:
        """Stable adapter/policy version suitable for audit persistence."""
        ...

    async def assess(self, request: ModerationRequest) -> ModerationAssessment:
        """Return normalized moderation evidence without taking external action."""
        ...


class ClassificationAdapter(Protocol):
    """Structured routing-only semantic classifier boundary."""

    @property
    def name(self) -> str:
        """Stable adapter identifier suitable for audit persistence."""
        ...

    @property
    def version(self) -> str:
        """Stable adapter/model version suitable for audit persistence."""
        ...

    async def classify(self, request: ClassificationRequest) -> ClassificationAssessment:
        """Return structured routing evidence; never answer the user."""
        ...


class SupervisorTransportAdapter(Protocol):
    """Provider-neutral boundary for dispatching one human escalation."""

    @property
    def name(self) -> str:
        """Stable transport identifier suitable for audit metadata."""
        ...

    async def dispatch(self, request: SupervisorDispatchRequest) -> str:
        """Dispatch an escalation and return an external conversation/thread id."""
        ...


class FatwaBridgeAdapter(Protocol):
    """Boundary for sending a question to the external supervised fatwa system."""

    @property
    def name(self) -> str:
        """Stable bridge identifier suitable for audit metadata."""
        ...

    async def dispatch(self, request: FatwaBridgeDispatch) -> str:
        """Dispatch a question and return a stable external case identifier."""
        ...
