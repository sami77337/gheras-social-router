"""Sandbox-gated GET-only Facebook and Instagram historical acquisition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

import httpx

from app.acquisition.common import (
    AcquiredComment,
    AcquisitionBatch,
    AcquisitionLimitExceeded,
    AcquisitionProtocolError,
    bounded_id,
    bounded_text,
    store_acquired_comment,
)
from app.adapters.platforms.live_security import validate_meta_graph_api_version
from app.domain.events import Platform
from app.integrations.live.activation import SandboxExecutionPermit
from app.integrations.live.base import ProviderProtocolError, request_json

_META_GRAPH_BASE = "https://graph.facebook.com"
_MAX_PAGES_PER_SOURCE = 100
_MAX_REPLIES_PAGES = 50
_MAX_COMMENTS = 20_000


def _credential(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProviderProtocolError(
            provider="meta",
            operation="configure_historical_reader",
            reason="missing or invalid access token",
        )
    if len(value) > 8192:
        raise ProviderProtocolError(
            provider="meta",
            operation="configure_historical_reader",
            reason="access token exceeds maximum length",
        )
    return value


def _object(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise AcquisitionProtocolError(f"{field} must be an object")
    return value


def _data(payload: Mapping[str, Any], *, field: str) -> list[object]:
    value = payload.get("data")
    if not isinstance(value, list):
        raise AcquisitionProtocolError(f"{field}.data must be a list")
    return value


def _after_cursor(payload: Mapping[str, Any], *, field: str) -> str | None:
    paging = payload.get("paging")
    if paging is None:
        return None
    paging_obj = _object(paging, field=f"{field}.paging")
    cursors = paging_obj.get("cursors")
    if cursors is None:
        return None
    cursor_obj = _object(cursors, field=f"{field}.paging.cursors")
    after = cursor_obj.get("after")
    if after is None:
        return None
    return bounded_id(after, field=f"{field}.paging.after")


class MetaHistoricalCommentClient:
    """GET-only Graph API reader for explicit post/media identifiers."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        permit: SandboxExecutionPermit | None,
        access_token: str,
        api_version: str,
    ) -> None:
        self._http = http
        self._permit = permit
        self._access_token = _credential(access_token)
        self._api_version = validate_meta_graph_api_version(api_version)

    async def _get(
        self,
        *,
        platform: Platform,
        operation: str,
        object_id: str,
        edge: str,
        fields: str,
        after: str | None,
    ) -> Mapping[str, Any]:
        object_ref = quote(bounded_id(object_id, field="object_id"), safe="")
        params: dict[str, str | int] = {
            "fields": fields,
            "limit": 100,
        }
        if after is not None:
            params["after"] = after
        return await request_json(
            http=self._http,
            permit=self._permit,
            provider=platform.value,
            operation=operation,
            method="GET",
            url=f"{_META_GRAPH_BASE}/{self._api_version}/{object_ref}/{edge}",
            headers={"Authorization": f"Bearer {self._access_token}"},
            params=params,
        )

    async def collect_facebook_posts(
        self,
        post_ids: Sequence[str],
        *,
        max_pages_per_source: int = _MAX_PAGES_PER_SOURCE,
    ) -> AcquisitionBatch:
        return await self._collect_sources(
            Platform.FACEBOOK,
            post_ids,
            text_field="message",
            replies_edge="comments",
            max_pages_per_source=max_pages_per_source,
        )

    async def collect_instagram_media(
        self,
        media_ids: Sequence[str],
        *,
        max_pages_per_source: int = _MAX_PAGES_PER_SOURCE,
    ) -> AcquisitionBatch:
        return await self._collect_sources(
            Platform.INSTAGRAM,
            media_ids,
            text_field="text",
            replies_edge="replies",
            max_pages_per_source=max_pages_per_source,
        )

    async def _collect_sources(
        self,
        platform: Platform,
        source_ids: Sequence[str],
        *,
        text_field: str,
        replies_edge: str,
        max_pages_per_source: int,
    ) -> AcquisitionBatch:
        if not 1 <= max_pages_per_source <= _MAX_PAGES_PER_SOURCE:
            raise AcquisitionProtocolError(
                "max_pages_per_source is outside the allowed range"
            )
        normalized_sources = tuple(
            bounded_id(source_id, field="source_id") for source_id in source_ids
        )
        if not normalized_sources:
            raise AcquisitionProtocolError("at least one source id is required")

        comments: dict[str, AcquiredComment] = {}
        for source_id in normalized_sources:
            await self._collect_comment_edge(
                platform=platform,
                source_id=source_id,
                parent_id=source_id,
                edge="comments",
                text_field=text_field,
                replies_edge=replies_edge,
                comments=comments,
                max_pages=max_pages_per_source,
                collect_replies=True,
            )
            if len(comments) > _MAX_COMMENTS:
                raise AcquisitionLimitExceeded(
                    f"{platform.value} acquisition exceeds maximum comment count"
                )

        source_ref = ",".join(sorted(normalized_sources))
        return AcquisitionBatch.build(
            platform=platform,
            source_ref=source_ref,
            comments=tuple(comments.values()),
        )

    async def _collect_comment_edge(
        self,
        *,
        platform: Platform,
        source_id: str,
        parent_id: str,
        edge: str,
        text_field: str,
        replies_edge: str,
        comments: dict[str, AcquiredComment],
        max_pages: int,
        collect_replies: bool,
    ) -> None:
        after: str | None = None
        for _ in range(max_pages):
            payload = await self._get(
                platform=platform,
                operation=f"historical_{edge}",
                object_id=parent_id,
                edge=edge,
                fields=f"id,{text_field}",
                after=after,
            )
            for raw in _data(payload, field=edge):
                comment = _object(raw, field="comment")
                comment_id = bounded_id(comment.get("id"), field="comment.id")
                raw_text = comment.get(text_field)
                if isinstance(raw_text, str) and raw_text.strip():
                    text = bounded_text(raw_text, field=f"comment.{text_field}")
                    store_acquired_comment(
                        comments,
                        AcquiredComment(
                            platform=platform,
                            comment_id=comment_id,
                            source_id=source_id,
                            thread_id=parent_id if parent_id != source_id else comment_id,
                            text=text,
                        ),
                    )
                    if len(comments) > _MAX_COMMENTS:
                        raise AcquisitionLimitExceeded(
                            f"{platform.value} acquisition exceeds maximum comment count"
                        )
                if collect_replies:
                    await self._collect_comment_edge(
                        platform=platform,
                        source_id=source_id,
                        parent_id=comment_id,
                        edge=replies_edge,
                        text_field=text_field,
                        replies_edge=replies_edge,
                        comments=comments,
                        max_pages=_MAX_REPLIES_PAGES,
                        collect_replies=False,
                    )
            after = _after_cursor(payload, field=edge)
            if after is None:
                return
        if after is not None:
            raise AcquisitionLimitExceeded(
                f"{platform.value} {edge} pagination limit reached"
            )
