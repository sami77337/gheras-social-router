"""YouTube polling-to-durable-ingress coordinator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.adapters.platforms.youtube import YouTubeAdapter, YouTubeCommentDTO
from app.domain.events import NormalizedInboundEvent
from app.ingress.common import (
    ExactIngestionCollector,
    IngressBatchResult,
    IngressPayloadError,
    list_value,
    mapping,
    provider_id,
    provider_text,
)


class YouTubeThreadSource(Protocol):
    """Minimal source contract implemented by the Phase 12 YouTube client."""

    async def list_comment_threads(
        self,
        *,
        video_id: str,
        page_token: str | None = None,
        max_results: int | None = None,
    ) -> Mapping[str, Any]:
        """Return one provider comment-thread page."""
        ...


@dataclass(frozen=True, slots=True)
class YouTubePollResult:
    """Redaction-safe polling result without retaining the provider response."""

    batch: IngressBatchResult
    next_page_token: str | None


def _comment_text(snippet: dict[str, Any]) -> str:
    original = snippet.get("textOriginal")
    if isinstance(original, str) and original.strip():
        return provider_text(original, field="youtube.textOriginal")
    return provider_text(snippet.get("textDisplay"), field="youtube.textDisplay")


def _author_channel_id(snippet: dict[str, Any]) -> str:
    author_channel = mapping(
        snippet.get("authorChannelId"),
        field="youtube.authorChannelId",
    )
    return provider_id(author_channel.get("value"), field="youtube.authorChannelId.value")


def _decode_top_level_comment(
    raw_item: Any,
    *,
    expected_video_id: str,
    own_channel_id: str,
) -> tuple[NormalizedInboundEvent | None, bool]:
    item = mapping(raw_item, field="youtube.items[]")
    thread_id = provider_id(item.get("id"), field="youtube.thread_id")
    thread_snippet = mapping(item.get("snippet"), field="youtube.thread.snippet")
    video_id = provider_id(thread_snippet.get("videoId"), field="youtube.video_id")
    if video_id != expected_video_id:
        raise IngressPayloadError("YouTube response video id does not match polling target")

    top_level = mapping(
        thread_snippet.get("topLevelComment"),
        field="youtube.topLevelComment",
    )
    comment_id = provider_id(top_level.get("id"), field="youtube.comment_id")
    snippet = mapping(top_level.get("snippet"), field="youtube.comment.snippet")
    try:
        author_id = _author_channel_id(snippet)
    except IngressPayloadError:
        return None, True
    if author_id == own_channel_id:
        return None, True

    try:
        normalized = YouTubeAdapter.normalize(
            YouTubeCommentDTO(
                comment_id=comment_id,
                video_id=video_id,
                author_channel_id=author_id,
                text=_comment_text(snippet),
                thread_id=thread_id,
            )
        )
    except ValueError as exc:
        raise IngressPayloadError(str(exc)) from None
    return normalized, False


class YouTubePollingIngress:
    """Poll supported top-level YouTube comments and persist normalized evidence."""

    def __init__(
        self,
        *,
        source: YouTubeThreadSource,
        collector: ExactIngestionCollector,
        own_channel_id: str,
    ) -> None:
        self._source = source
        self._collector = collector
        self._own_channel_id = provider_id(own_channel_id, field="youtube.own_channel_id")

    async def poll_video(
        self,
        *,
        video_id: str,
        page_token: str | None = None,
        max_results: int | None = None,
    ) -> YouTubePollResult:
        target_video = provider_id(video_id, field="youtube.poll_video_id")
        payload = await self._source.list_comment_threads(
            video_id=target_video,
            page_token=page_token,
            max_results=max_results,
        )
        if not isinstance(payload, Mapping):
            raise IngressPayloadError("YouTube polling response must be an object")

        items = list_value(payload.get("items"), field="youtube.items")
        normalized: list[NormalizedInboundEvent] = []
        ignored = 0
        for item in items:
            event, was_ignored = _decode_top_level_comment(
                item,
                expected_video_id=target_video,
                own_channel_id=self._own_channel_id,
            )
            if event is not None:
                normalized.append(event)
            ignored += int(was_ignored)

        next_page = payload.get("nextPageToken")
        if next_page is not None:
            next_page = provider_id(next_page, field="youtube.nextPageToken")

        results = tuple(self._collector.ingest(event) for event in normalized)
        return YouTubePollResult(
            batch=IngressBatchResult(results=results, ignored_count=ignored),
            next_page_token=next_page,
        )
