"""Sandbox-capable Telegram Bot API transport client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx

from app.adapters.platforms.common import reply_text, required_id, required_text
from app.adapters.platforms.telegram import TelegramReplyClient, TelegramSupervisorClient
from app.integrations.live.activation import SandboxExecutionPermit
from app.integrations.live.base import ProviderProtocolError, request_json

_TELEGRAM_API_BASE = "https://api.telegram.org"


def _bot_token(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProviderProtocolError(
            provider="telegram",
            operation="configure",
            reason="missing or invalid bot token",
        )
    if len(value) > 8192:
        raise ProviderProtocolError(
            provider="telegram",
            operation="configure",
            reason="bot token exceeds maximum length",
        )
    return value


def _message_id(payload: Mapping[str, Any], *, operation: str) -> str:
    if payload.get("ok") is not True:
        raise ProviderProtocolError(
            provider="telegram",
            operation=operation,
            reason="response did not report success",
        )
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ProviderProtocolError(
            provider="telegram",
            operation=operation,
            reason="response result is missing",
        )
    value = result.get("message_id")
    if isinstance(value, int) and value > 0:
        return str(value)
    raise ProviderProtocolError(
        provider="telegram",
        operation=operation,
        reason="response message_id is invalid",
    )


def _reply_target(target_id: str) -> tuple[int, int]:
    target = required_id(target_id, field="target_id")
    if ":" not in target:
        raise ProviderProtocolError(
            provider="telegram",
            operation="parse_reply_target",
            reason="target must contain chat_id:message_id",
        )
    chat_raw, message_raw = target.rsplit(":", 1)
    try:
        chat_id = int(chat_raw)
        message_id = int(message_raw)
    except ValueError:
        raise ProviderProtocolError(
            provider="telegram",
            operation="parse_reply_target",
            reason="target ids must be integers",
        ) from None
    if message_id <= 0:
        raise ProviderProtocolError(
            provider="telegram",
            operation="parse_reply_target",
            reason="message_id must be positive",
        )
    return chat_id, message_id


class TelegramBotClient(TelegramReplyClient, TelegramSupervisorClient):
    """Reply and supervisor transport implementation via injected HTTP."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        permit: SandboxExecutionPermit | None,
        bot_token: str,
        supervisor_chat_id: str,
    ) -> None:
        self._http = http
        self._permit = permit
        self._bot_token = _bot_token(bot_token)
        self._supervisor_chat_id = required_id(
            supervisor_chat_id,
            field="supervisor_chat_id",
        )

    def _send_message_url(self) -> str:
        encoded_token = quote(self._bot_token, safe=":")
        return f"{_TELEGRAM_API_BASE}/bot{encoded_token}/sendMessage"

    async def reply_to_message(self, target_id: str, text: str) -> str:
        chat_id, message_id = _reply_target(target_id)
        payload = await request_json(
            http=self._http,
            permit=self._permit,
            provider="telegram",
            operation="reply_to_message",
            method="POST",
            url=self._send_message_url(),
            json_body={
                "chat_id": chat_id,
                "text": reply_text(text),
                "reply_parameters": {"message_id": message_id},
            },
        )
        return _message_id(payload, operation="reply_to_message")

    async def send_supervisor_message(self, text: str) -> str:
        payload = await request_json(
            http=self._http,
            permit=self._permit,
            provider="telegram",
            operation="send_supervisor_message",
            method="POST",
            url=self._send_message_url(),
            json_body={
                "chat_id": self._supervisor_chat_id,
                "text": required_text(text, field="supervisor_text"),
            },
        )
        return _message_id(payload, operation="send_supervisor_message")
