"""Protocol boundaries for future external integrations."""

from __future__ import annotations

from typing import Protocol


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
