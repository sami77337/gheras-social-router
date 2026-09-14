"""YouTube normalization and injectable reply boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.adapters.platforms.common import optional_id, reply_text, required_id, required_text
from app.domain.events import NormalizedInboundEvent, Platform


@dataclass(frozen=True, slots=True)
class YouTubeCommentDTO:
    """Boundary fields required from one YouTube comment/comment-thread item."""

    comment_id: str
    video_id: str
    author_channel_id: str
    text: str
    thread_id: str | None = None


class YouTubeAdapter:
    """Pure YouTube-to-domain normalizer."""

    @staticmethod
    def normalize(comment: YouTubeCommentDTO) -> NormalizedInboundEvent:
        comment_id = required_id(comment.comment_id, field="comment_id")
        thread_id = optional_id(comment.thread_id, field="thread_id")
        return NormalizedInboundEvent(
            platform=Platform.YOUTUBE,
            external_event_key=comment_id,
            external_event_id=thread_id or comment_id,
            external_comment_id=comment_id,
            external_post_id=required_id(comment.video_id, field="video_id"),
            author_id=required_id(
                comment.author_channel_id,
                field="author_channel_id",
            ),
            text=required_text(comment.text),
        )


class YouTubeReplyClient(Protocol):
    """Injected client boundary; production implementation belongs to live integration."""

    async def reply_to_comment(self, comment_id: str, text: str) -> str:
        """Return the created YouTube reply identifier."""
        ...


class YouTubeReplyPublisher:
    """YouTube reply adapter backed only by an injected client."""

    def __init__(self, client: YouTubeReplyClient) -> None:
        self.client = client

    async def publish_reply(self, *, external_comment_id: str, text: str) -> str:
        target = required_id(external_comment_id, field="external_comment_id")
        result = await self.client.reply_to_comment(target, reply_text(text))
        return required_id(result, field="external_result_id")
