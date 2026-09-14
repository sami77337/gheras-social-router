from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from urllib.parse import parse_qs

import httpx
import pytest

from app.integrations.live.activation import (
    ExternalIntegrationDisabled,
    issue_sandbox_execution_permit,
)
from app.integrations.live.base import ProviderHTTPError, ProviderTransportError
from app.integrations.live.meta import FacebookGraphReplyClient, InstagramGraphReplyClient
from app.integrations.live.telegram import TelegramBotClient
from app.integrations.live.youtube import YouTubeDataClient


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


async def _with_client(
    handler: Callable[[httpx.Request], httpx.Response],
    callback: Callable[[httpx.AsyncClient], object],
) -> object:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = callback(http)
        if hasattr(result, "__await__"):
            return await result  # type: ignore[misc]
        return result


def test_facebook_reply_request_matches_verified_graph_contract() -> None:
    token = "meta-sandbox-token"
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "POST"
        assert request.url.host == "graph.facebook.com"
        assert request.url.path == "/v26.0/123_456/comments"
        assert request.headers["authorization"] == f"Bearer {token}"
        assert parse_qs(request.content.decode()) == {"message": ["جزاكم الله خيرًا"]}
        return httpx.Response(200, json={"id": "facebook-reply-id"})

    async def scenario(http: httpx.AsyncClient) -> str:
        client = FacebookGraphReplyClient(
            http=http,
            permit=issue_sandbox_execution_permit(purpose="sandbox_validation"),
            access_token=token,
            api_version="v26.0",
        )
        return await client.reply_to_comment("123_456", "جزاكم الله خيرًا")

    result = _run(_with_client(handler, scenario))
    assert result == "facebook-reply-id"
    assert len(seen) == 1


def test_instagram_reply_request_matches_verified_graph_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.host == "graph.facebook.com"
        assert request.url.path == "/v26.0/17890001/replies"
        assert parse_qs(request.content.decode()) == {"message": ["أهلًا بكم"]}
        return httpx.Response(200, json={"id": "instagram-reply-id"})

    async def scenario(http: httpx.AsyncClient) -> str:
        client = InstagramGraphReplyClient(
            http=http,
            permit=issue_sandbox_execution_permit(purpose="sandbox_validation"),
            access_token="meta-sandbox-token",
            api_version="v26.0",
        )
        return await client.reply_to_comment("17890001", "أهلًا بكم")

    assert _run(_with_client(handler, scenario)) == "instagram-reply-id"


def test_telegram_reply_uses_send_message_reply_parameters() -> None:
    token = "123456:telegram-sandbox-token"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.host == "api.telegram.org"
        assert request.url.path == f"/bot{token}/sendMessage"
        payload = json.loads(request.content)
        assert payload == {
            "chat_id": -100123,
            "text": "تم الاستلام",
            "reply_parameters": {"message_id": 77},
        }
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 88}})

    async def scenario(http: httpx.AsyncClient) -> str:
        client = TelegramBotClient(
            http=http,
            permit=issue_sandbox_execution_permit(purpose="sandbox_validation"),
            bot_token=token,
            supervisor_chat_id="-100999",
        )
        return await client.reply_to_message("-100123:77", "تم الاستلام")

    assert _run(_with_client(handler, scenario)) == "88"


def test_telegram_supervisor_transport_has_no_implicit_reply_target() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload == {"chat_id": "-100999", "text": "مراجعة بشرية مطلوبة"}
        assert "reply_parameters" not in payload
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 901}})

    async def scenario(http: httpx.AsyncClient) -> str:
        client = TelegramBotClient(
            http=http,
            permit=issue_sandbox_execution_permit(purpose="sandbox_validation"),
            bot_token="123456:telegram-sandbox-token",
            supervisor_chat_id="-100999",
        )
        return await client.send_supervisor_message("مراجعة بشرية مطلوبة")

    assert _run(_with_client(handler, scenario)) == "901"


class _TokenProvider:
    def __init__(self, token: str = "youtube-sandbox-token") -> None:
        self.token = token
        self.calls = 0

    async def get_access_token(self) -> str:
        self.calls += 1
        return self.token


def test_youtube_list_and_reply_match_verified_data_api_contracts() -> None:
    requests: list[httpx.Request] = []
    token_provider = _TokenProvider()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer youtube-sandbox-token"
        if request.url.path.endswith("/commentThreads"):
            assert request.method == "GET"
            assert request.url.params["part"] == "snippet,replies"
            assert request.url.params["videoId"] == "video-123"
            assert request.url.params["maxResults"] == "25"
            assert request.url.params["textFormat"] == "plainText"
            assert request.url.params["pageToken"] == "page-2"
            return httpx.Response(200, json={"items": [], "nextPageToken": "page-3"})

        assert request.url.path.endswith("/comments")
        assert request.method == "POST"
        assert request.url.params["part"] == "snippet"
        assert json.loads(request.content) == {
            "snippet": {
                "parentId": "comment-123",
                "textOriginal": "نص الرد كما هو",
            }
        }
        return httpx.Response(200, json={"id": "youtube-reply-id"})

    async def scenario(http: httpx.AsyncClient) -> tuple[object, str]:
        client = YouTubeDataClient(
            http=http,
            permit=issue_sandbox_execution_permit(purpose="sandbox_validation"),
            token_provider=token_provider,
        )
        page = await client.list_comment_threads(
            video_id="video-123",
            page_token="page-2",
            max_results=25,
        )
        reply_id = await client.reply_to_comment("comment-123", "نص الرد كما هو")
        return page, reply_id

    page, reply_id = _run(_with_client(handler, scenario))  # type: ignore[misc]
    assert page == {"items": [], "nextPageToken": "page-3"}
    assert reply_id == "youtube-reply-id"
    assert token_provider.calls == 2
    assert len(requests) == 2


def test_missing_permit_prevents_http_and_youtube_token_provider_calls() -> None:
    http_calls = 0
    token_provider = _TokenProvider()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        return httpx.Response(500, request=request)

    async def scenario(http: httpx.AsyncClient) -> None:
        facebook = FacebookGraphReplyClient(
            http=http,
            permit=None,
            access_token="meta-secret",
            api_version="v26.0",
        )
        with pytest.raises(ExternalIntegrationDisabled):
            await facebook.reply_to_comment("comment-1", "text")

        youtube = YouTubeDataClient(
            http=http,
            permit=None,
            token_provider=token_provider,
        )
        with pytest.raises(ExternalIntegrationDisabled):
            await youtube.list_comment_threads(video_id="video-1")

    _run(_with_client(handler, scenario))
    assert http_calls == 0
    assert token_provider.calls == 0


def test_provider_http_error_is_redacted_and_retry_classified() -> None:
    secret = "meta-super-secret-token"
    response_secret = "do-not-leak-response-body"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=response_secret, request=request)

    async def scenario(http: httpx.AsyncClient) -> None:
        client = FacebookGraphReplyClient(
            http=http,
            permit=issue_sandbox_execution_permit(purpose="sandbox_validation"),
            access_token=secret,
            api_version="v26.0",
        )
        with pytest.raises(ProviderHTTPError) as exc_info:
            await client.reply_to_comment("comment-1", "text")
        error = exc_info.value
        assert error.status_code == 503
        assert error.retryable is True
        rendered = repr(error) + str(error)
        assert secret not in rendered
        assert response_secret not in rendered
        assert "graph.facebook.com" not in rendered

    _run(_with_client(handler, scenario))


def test_transport_error_does_not_leak_underlying_exception_text() -> None:
    leaked = "transport-contained-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(leaked, request=request)

    async def scenario(http: httpx.AsyncClient) -> None:
        client = InstagramGraphReplyClient(
            http=http,
            permit=issue_sandbox_execution_permit(purpose="sandbox_validation"),
            access_token="meta-secret",
            api_version="v26.0",
        )
        with pytest.raises(ProviderTransportError) as exc_info:
            await client.reply_to_comment("comment-1", "text")
        rendered = repr(exc_info.value) + str(exc_info.value)
        assert leaked not in rendered
        assert "meta-secret" not in rendered

    _run(_with_client(handler, scenario))
