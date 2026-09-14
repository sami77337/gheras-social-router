"""Authenticated Telegram webhook decoding for V1 text messages."""

from __future__ import annotations

from app.adapters.platforms.live_security import verify_telegram_webhook_secret
from app.adapters.platforms.telegram import TelegramAdapter, TelegramMessageDTO
from app.ingress.common import (
    ExactIngestionCollector,
    IngressBatchResult,
    IngressPayloadError,
    load_json_object,
    mapping,
    provider_id,
    provider_text,
    validate_raw_body,
)


class TelegramWebhookIngress:
    """Verify Telegram's webhook secret before parsing and persist supported messages."""

    def __init__(self, *, collector: ExactIngestionCollector, webhook_secret: str) -> None:
        self._collector = collector
        self._webhook_secret = webhook_secret

    def ingest(self, *, raw_body: bytes, secret_header: str) -> IngressBatchResult:
        body = validate_raw_body(raw_body)
        verify_telegram_webhook_secret(
            supplied_header=secret_header,
            expected_secret=self._webhook_secret,
        )
        payload = load_json_object(body)

        if "message" not in payload:
            return IngressBatchResult(results=(), ignored_count=1)
        message = mapping(payload.get("message"), field="telegram.message")
        if "text" not in message:
            return IngressBatchResult(results=(), ignored_count=1)

        author = mapping(message.get("from"), field="telegram.message.from")
        if author.get("is_bot") is True:
            return IngressBatchResult(results=(), ignored_count=1)
        chat = mapping(message.get("chat"), field="telegram.message.chat")

        try:
            normalized = TelegramAdapter.normalize(
                TelegramMessageDTO(
                    update_id=provider_id(payload.get("update_id"), field="telegram.update_id"),
                    message_id=provider_id(
                        message.get("message_id"),
                        field="telegram.message_id",
                    ),
                    chat_id=provider_id(chat.get("id"), field="telegram.chat_id"),
                    author_id=provider_id(author.get("id"), field="telegram.author_id"),
                    text=provider_text(message.get("text"), field="telegram.text"),
                )
            )
        except ValueError as exc:
            raise IngressPayloadError(str(exc)) from None

        return IngressBatchResult(results=(self._collector.ingest(normalized),))
