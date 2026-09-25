"""Sandbox-gated GET-only YouTube historical comment acquisition."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from app.acquisition.common import (
    AcquiredComment,
    AcquisitionBatch,
    AcquisitionLimitExceeded,
    AcquisitionProtocolError,
    bounded_id,
    bounded_text,
)
from app.domain.events import Platform
from app.integrations.live.activation import SandboxExecutionPermit
from app.integrations.live.base import ProviderProtocolError, request_json

_YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
_MAX_PAGES = 250
_MAX_REPLY_PAGES_PER_THREAD = 50
_MAX_COMMENTS = 20_000


def _api_key(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProviderProtocolError(
            provider="youtube",
            operation="configure_historical_reader",
            reason="missing or invalid API key",
        )
    if len(value) > 4096 or any(char.isspace() for char in value):
        raise ProviderProtocolError(
            provider="youtube",
            operation="configure_historical_reader",
            reason="invalid API key",
        )
    return value


def _object(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise AcquisitionProtocolError(f"{field} must be an object")
    return value


def _list_field(
    payload: Mapping[str, Any],
    *,
    key: str,
    field: str,
) -> list[object]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise AcquisitionProtocolError(f"{field} must be a list")
    return value


def _next_page(payload: Mapping[str, Any], *, field: str) -> str | None:
    token = payload.get("nextPageToken")
    if token is None:
        return None
    return bounded_id(token, field=f"{field}.nextPageToken")


class YouTubeHistoricalCommentClient:
    """GET-only YouTube reader using an injected HTTP client and API key."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        permit: SandboxExecutionPermit | None,
        api_key: str,
    ) -> None:
        self._http = http
        self._permit = permit
        self._api_key = _api_key(api_key)

    async def _get(
        self,
        *,
        operation: str,
        endpoint: str,
        params: Mapping[str, str | int],
    ) -> Mapping[str, Any]:
        request_params = dict(params)
        request_params["key"] = self._api_key
        return await request_json(
            http=self._http,
            permit=self._permit,
            provider="youtube",
            operation=operation,
            method="GET",
            url=f"{_YOUTUBE_API_BASE}/{endpoint}",
            params=request_params,
        )

    async def collect_channel(
        self,
        channel_id: str,
        *,
        max_pages: int = _MAX_PAGES,
        max_reply_pages_per_thread: int = _MAX_REPLY_PAGES_PER_THREAD,
    ) -> AcquisitionBatch:
        channel = bounded_id(channel_id, field="channel_id")
        if not 1 <= max_pages <= _MAX_PAGES:
            raise AcquisitionProtocolError("max_pages is outside the allowed range")
        if not 1 <= max_reply_pages_per_thread <= _MAX_REPLY_PAGES_PER_THREAD:
            raise AcquisitionProtocolError(
                "max_reply_pages_per_thread is outside the allowed range"
            )

        comments: dict[str, AcquiredComment] = {}
        page_token: str | None = None

        for _ in range(max_pages):
            params: dict[str, str | int] = {
                "part": "snippet,replies",
                "allThreadsRelatedToChannelId": channel,
                "maxResults": 100,
                "textFormat": "plainText",
                "order": "time",
            }
            if page_token is not None:
                params["pageToken"] = page_token

            payload = await self._get(
                operation="historical_comment_threads",
                endpoint="commentThreads",
                params=params,
            )
            for raw_thread in _list_field(
                payload,
                key="items",
                field="commentThreads.items",
            ):
                thread = _object(raw_thread, field="commentThread")
                await self._consume_thread(
                    thread,
                    comments=comments,
                    max_reply_pages=max_reply_pages_per_thread,
                )
                if len(comments) > _MAX_COMMENTS:
                    raise AcquisitionLimitExceeded(
                        "YouTube acquisition exceeds maximum comment count"
                    )

            page_token = _next_page(payload, field="commentThreads")
            if page_token is None:
                break
        else:
            if page_token is not None:
                raise AcquisitionLimitExceeded("YouTube thread pagination limit reached")

        return AcquisitionBatch.build(
            platform=Platform.YOUTUBE,
            source_ref=channel,
            comments=tuple(comments.values()),
        )

    async def _consume_thread(
        self,
        thread: Mapping[str, Any],
        *,
        comments: dict[str, AcquiredComment],
        max_reply_pages: int,
    ) -> None:
        thread_id = bounded_id(thread.get("id"), field="thread.id")
        snippet = _object(thread.get("snippet"), field="thread.snippet")
        video_id = bounded_id(snippet.get("videoId"), field="thread.videoId")
        top = _object(snippet.get("topLevelComment"), field="thread.topLevelComment")
        top_id = bounded_id(top.get("id"), field="topLevelComment.id")
        top_snippet = _object(top.get("snippet"), field="topLevelComment.snippet")
        top_text = bounded_text(
            top_snippet.get("textOriginal", top_snippet.get("textDisplay")),
            field="topLevelComment.text",
        )
        comments[top_id] = AcquiredComment(
            platform=Platform.YOUTUBE,
            comment_id=top_id,
            source_id=video_id,
            thread_id=thread_id,
            text=top_text,
        )

        replies_obj = thread.get("replies")
        inline_replies: list[object] = []
        if replies_obj is not None:
            inline_replies = _list_field(
                _object(replies_obj, field="thread.replies"),
                key="comments",
                field="thread.replies.comments",
            )
        for raw_reply in inline_replies:
            self._consume_reply(
                _object(raw_reply, field="reply"),
                video_id=video_id,
                thread_id=thread_id,
                comments=comments,
            )

        total_reply_count = snippet.get("totalReplyCount", 0)
        if not isinstance(total_reply_count, int) or total_reply_count < 0:
            raise AcquisitionProtocolError("thread.totalReplyCount must be non-negative")
        if total_reply_count > len(inline_replies):
            await self._collect_all_replies(
                parent_id=top_id,
                video_id=video_id,
                thread_id=thread_id,
                comments=comments,
                max_pages=max_reply_pages,
            )

    def _consume_reply(
        self,
        reply: Mapping[str, Any],
        *,
        video_id: str,
        thread_id: str,
        comments: dict[str, AcquiredComment],
    ) -> None:
        comment_id = bounded_id(reply.get("id"), field="reply.id")
        snippet = _object(reply.get("snippet"), field="reply.snippet")
        text = bounded_text(
            snippet.get("textOriginal", snippet.get("textDisplay")),
            field="reply.text",
        )
        comments[comment_id] = AcquiredComment(
            platform=Platform.YOUTUBE,
            comment_id=comment_id,
            source_id=video_id,
            thread_id=thread_id,
            text=text,
        )

    async def _collect_all_replies(
        self,
        *,
        parent_id: str,
        video_id: str,
        thread_id: str,
        comments: dict[str, AcquiredComment],
        max_pages: int,
    ) -> None:
        page_token: str | None = None
        for _ in range(max_pages):
            params: dict[str, str | int] = {
                "part": "snippet",
                "parentId": parent_id,
                "maxResults": 100,
                "textFormat": "plainText",
            }
            if page_token is not None:
                params["pageToken"] = page_token
            payload = await self._get(
                operation="historical_comment_replies",
                endpoint="comments",
                params=params,
            )
            for raw_reply in _list_field(
                payload,
                key="items",
                field="comments.items",
            ):
                self._consume_reply(
                    _object(raw_reply, field="reply"),
                    video_id=video_id,
                    thread_id=thread_id,
                    comments=comments,
                )
            page_token = _next_page(payload, field="comments")
            if page_token is None:
                return
        if page_token is not None:
            raise AcquisitionLimitExceeded("YouTube reply pagination limit reached")
