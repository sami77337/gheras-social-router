"""Facebook normalization and injectable reply boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.adapters.platforms.common import optional_id, reply_text, required_id, required_text
from app.domain.events import NormalizedInboundEvent, Platform


@dataclass(frozen=True, slots=True)
class FacebookCommentDTO:
    """Validated boundary fields required from a Facebook comment delivery."""

    comment_id: str
    post_id: str
    author_id: str
    text: str
    event_id: str | None = None


class FacebookAdapter:
    """Pure Facebook-to-domain normalizer."""

    @staticmethod
    def normalize(comment: FacebookCommentDTO) -> NormalizedInboundEvent:
        comment_id = required_id(comment.comment_id, field="comment_id")
        return NormalizedInboundEvent(
            platform=Platform.FACEBOOK,
            external_event_key=comment_id,
            external_event_id=optional_id(comment.event_id, field="event_id"),
            external_comment_id=comment_id,
            external_post_id=required_id(comment.post_id, field="post_id"),
            author_id=required_id(comment.author_id, field="author_id"),
            text=required_text(comment.text),
        )


class FacebookReplyClient(Protocol):
    """Injected client boundary; production implementation belongs to live integration."""

    async def reply_to_comment(self, comment_id: str, text: str) -> str:
        """Return the created Facebook reply identifier."""
        ...


class FacebookReplyPublisher:
    """Facebook reply adapter backed only by an injected client."""

    def __init__(self, client: FacebookReplyClient) -> None:
        self.client = client

    async def publish_reply(self, *, external_comment_id: str, text: str) -> str:
        target = required_id(external_comment_id, field="external_comment_id")
        result = await self.client.reply_to_comment(target, reply_text(text))
        return required_id(result, field="external_result_id")
