"""Telegram normalization, reply, and supervisor transport boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.adapters.platforms.common import reply_text, required_id, required_text
from app.domain.events import NormalizedInboundEvent, Platform
from app.domain.supervisor import SupervisorDispatchRequest


@dataclass(frozen=True, slots=True)
class TelegramMessageDTO:
    """Boundary fields required from one Telegram update/message."""

    update_id: str
    message_id: str
    chat_id: str
    author_id: str
    text: str


class TelegramAdapter:
    """Pure Telegram-to-domain normalizer."""

    @staticmethod
    def normalize(message: TelegramMessageDTO) -> NormalizedInboundEvent:
        update_id = required_id(message.update_id, field="update_id")
        message_id = required_id(message.message_id, field="message_id")
        chat_id = required_id(message.chat_id, field="chat_id")
        target = f"{chat_id}:{message_id}"
        return NormalizedInboundEvent(
            platform=Platform.TELEGRAM,
            external_event_key=target,
            external_event_id=update_id,
            external_comment_id=target,
            external_post_id=chat_id,
            author_id=required_id(message.author_id, field="author_id"),
            text=required_text(message.text),
        )


class TelegramReplyClient(Protocol):
    """Injected client boundary for replies to an opaque Telegram message target."""

    async def reply_to_message(self, target_id: str, text: str) -> str:
        """Return the created Telegram message identifier."""
        ...


class TelegramReplyPublisher:
    """Telegram reply adapter backed only by an injected client."""

    def __init__(self, client: TelegramReplyClient) -> None:
        self.client = client

    async def publish_reply(self, *, external_comment_id: str, text: str) -> str:
        target = required_id(external_comment_id, field="external_comment_id")
        result = await self.client.reply_to_message(target, reply_text(text))
        return required_id(result, field="external_result_id")


class TelegramSupervisorClient(Protocol):
    """Injected Telegram client for human-review dispatch only."""

    async def send_supervisor_message(self, text: str) -> str:
        """Return the Telegram thread/message identifier used for the escalation."""
        ...


class TelegramSupervisorTransport:
    """Supervisor transport adapter with deterministic plain-text formatting."""

    name = "telegram"

    def __init__(self, client: TelegramSupervisorClient) -> None:
        self.client = client

    async def dispatch(self, request: SupervisorDispatchRequest) -> str:
        message = self._format(request)
        result = await self.client.send_supervisor_message(message)
        return required_id(result, field="external_thread_id")

    @staticmethod
    def _format(request: SupervisorDispatchRequest) -> str:
        text = request.text if request.text is not None else "[no text]"
        return (
            "[GHERAS SUPERVISOR]\n"
            f"escalation_id={required_id(request.escalation_id, field='escalation_id')}\n"
            f"event_id={required_id(request.event_id, field='event_id')}\n"
            f"platform={required_id(request.platform, field='platform')}\n"
            f"correlation_id={required_id(request.correlation_id, field='correlation_id')}\n"
            f"text={text}"
        )
