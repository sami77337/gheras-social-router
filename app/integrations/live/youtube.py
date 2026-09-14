"""Sandbox-capable YouTube Data API comment polling and reply client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

import httpx

from app.adapters.platforms.common import optional_id, reply_text, required_id
from app.adapters.platforms.live_security import YouTubePollingPolicy
from app.adapters.platforms.youtube import YouTubeReplyClient
from app.integrations.live.activation import (
    SandboxExecutionPermit,
    require_sandbox_execution,
)
from app.integrations.live.base import ProviderProtocolError, request_json, required_response_id

_YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeAccessTokenProvider(Protocol):
    """Provides a short-lived OAuth access token outside this HTTP client."""

    async def get_access_token(self) -> str:
        """Return one current OAuth access token."""
        ...


def _access_token(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProviderProtocolError(
            provider="youtube",
            operation="authorize",
            reason="missing or invalid access token",
        )
    if len(value) > 8192:
        raise ProviderProtocolError(
            provider="youtube",
            operation="authorize",
            reason="access token exceeds maximum length",
        )
    return value


class YouTubeDataClient(YouTubeReplyClient):
    """YouTube reply protocol plus comment-thread polling through injected HTTP."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        permit: SandboxExecutionPermit | None,
        token_provider: YouTubeAccessTokenProvider,
        polling_policy: YouTubePollingPolicy | None = None,
    ) -> None:
        self._http = http
        self._permit = permit
        self._token_provider = token_provider
        self._polling_policy = polling_policy or YouTubePollingPolicy()

    async def _authorization_header(self) -> Mapping[str, str]:
        require_sandbox_execution(self._permit)
        token = _access_token(await self._token_provider.get_access_token())
        return {"Authorization": f"Bearer {token}"}

    async def list_comment_threads(
        self,
        *,
        video_id: str,
        page_token: str | None = None,
        max_results: int | None = None,
    ) -> Mapping[str, Any]:
        video = required_id(video_id, field="video_id")
        page = optional_id(page_token, field="page_token")
        limit = (
            self._polling_policy.max_results_per_page
            if max_results is None
            else max_results
        )
        if not 1 <= limit <= self._polling_policy.max_results_per_page:
            raise ProviderProtocolError(
                provider="youtube",
                operation="list_comment_threads",
                reason="max_results exceeds configured polling policy",
            )

        params: dict[str, str | int] = {
            "part": "snippet,replies",
            "videoId": video,
            "maxResults": limit,
            "textFormat": "plainText",
        }
        if page is not None:
            params["pageToken"] = page

        payload = await request_json(
            http=self._http,
            permit=self._permit,
            provider="youtube",
            operation="list_comment_threads",
            method="GET",
            url=f"{_YOUTUBE_API_BASE}/commentThreads",
            headers=await self._authorization_header(),
            params=params,
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise ProviderProtocolError(
                provider="youtube",
                operation="list_comment_threads",
                reason="response items must be a list",
            )
        next_page = payload.get("nextPageToken")
        if next_page is not None and not isinstance(next_page, str):
            raise ProviderProtocolError(
                provider="youtube",
                operation="list_comment_threads",
                reason="nextPageToken must be a string when present",
            )
        return payload

    async def reply_to_comment(self, comment_id: str, text: str) -> str:
        parent_id = required_id(comment_id, field="comment_id")
        payload = await request_json(
            http=self._http,
            permit=self._permit,
            provider="youtube",
            operation="reply_to_comment",
            method="POST",
            url=f"{_YOUTUBE_API_BASE}/comments",
            headers=await self._authorization_header(),
            params={"part": "snippet"},
            json_body={
                "snippet": {
                    "parentId": parent_id,
                    "textOriginal": reply_text(text),
                }
            },
        )
        return required_response_id(
            payload,
            provider="youtube",
            operation="reply_to_comment",
        )
