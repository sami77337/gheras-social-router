"""Sandbox-capable Facebook and Instagram Graph API reply clients."""

from __future__ import annotations

from urllib.parse import quote

import httpx

from app.adapters.platforms.common import reply_text, required_id
from app.adapters.platforms.facebook import FacebookReplyClient
from app.adapters.platforms.instagram import InstagramReplyClient
from app.adapters.platforms.live_security import validate_meta_graph_api_version
from app.integrations.live.activation import SandboxExecutionPermit
from app.integrations.live.base import ProviderProtocolError, request_json, required_response_id

_META_GRAPH_BASE = "https://graph.facebook.com"


def _credential(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProviderProtocolError(
            provider="meta",
            operation="configure",
            reason=f"missing or invalid {field}",
        )
    if len(value) > 8192:
        raise ProviderProtocolError(
            provider="meta",
            operation="configure",
            reason=f"{field} exceeds maximum length",
        )
    return value


class FacebookGraphReplyClient(FacebookReplyClient):
    """FacebookReplyClient implementation through an injected HTTP client."""

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
        self._access_token = _credential(access_token, field="access_token")
        self._api_version = validate_meta_graph_api_version(api_version)

    async def reply_to_comment(self, comment_id: str, text: str) -> str:
        comment = quote(required_id(comment_id, field="comment_id"), safe="")
        url = f"{_META_GRAPH_BASE}/{self._api_version}/{comment}/comments"
        payload = await request_json(
            http=self._http,
            permit=self._permit,
            provider="facebook",
            operation="reply_to_comment",
            method="POST",
            url=url,
            headers={"Authorization": f"Bearer {self._access_token}"},
            data={"message": reply_text(text)},
        )
        return required_response_id(
            payload,
            provider="facebook",
            operation="reply_to_comment",
        )


class InstagramGraphReplyClient(InstagramReplyClient):
    """InstagramReplyClient implementation for Facebook Login mode."""

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
        self._access_token = _credential(access_token, field="access_token")
        self._api_version = validate_meta_graph_api_version(api_version)

    async def reply_to_comment(self, comment_id: str, text: str) -> str:
        comment = quote(required_id(comment_id, field="comment_id"), safe="")
        url = f"{_META_GRAPH_BASE}/{self._api_version}/{comment}/replies"
        payload = await request_json(
            http=self._http,
            permit=self._permit,
            provider="instagram",
            operation="reply_to_comment",
            method="POST",
            url=url,
            headers={"Authorization": f"Bearer {self._access_token}"},
            data={"message": reply_text(text)},
        )
        return required_response_id(
            payload,
            provider="instagram",
            operation="reply_to_comment",
        )
