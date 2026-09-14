"""Authenticated Meta webhook decoding for Facebook and Instagram comments."""

from __future__ import annotations

from typing import Any

from app.adapters.platforms.facebook import FacebookAdapter, FacebookCommentDTO
from app.adapters.platforms.instagram import InstagramAdapter, InstagramCommentDTO
from app.adapters.platforms.live_security import verify_meta_signature
from app.domain.events import NormalizedInboundEvent
from app.ingress.common import (
    ExactIngestionCollector,
    IngressBatchResult,
    IngressPayloadError,
    UnsupportedIngressEvent,
    list_value,
    load_json_object,
    mapping,
    provider_id,
    provider_text,
    validate_raw_body,
)


def _normalize_facebook(
    *,
    entry_id: str,
    change: dict[str, Any],
) -> tuple[NormalizedInboundEvent | None, bool]:
    if change.get("field") != "feed":
        return None, True
    value = mapping(change.get("value"), field="facebook.change.value")
    if value.get("item") != "comment" or value.get("verb") != "add":
        return None, True
    if "message" not in value:
        return None, True

    author = mapping(value.get("from"), field="facebook.change.value.from")
    author_id = provider_id(author.get("id"), field="facebook.author_id")
    if author_id == entry_id:
        return None, True

    try:
        normalized = FacebookAdapter.normalize(
            FacebookCommentDTO(
                comment_id=provider_id(
                    value.get("comment_id"),
                    field="facebook.comment_id",
                ),
                post_id=provider_id(value.get("post_id"), field="facebook.post_id"),
                author_id=author_id,
                text=provider_text(value.get("message"), field="facebook.message"),
            )
        )
    except ValueError as exc:
        raise IngressPayloadError(str(exc)) from None
    return normalized, False


def _facebook_events(payload: dict[str, Any]) -> tuple[list[NormalizedInboundEvent], int]:
    entries = list_value(payload.get("entry"), field="facebook.entry")
    events: list[NormalizedInboundEvent] = []
    ignored = 0
    for raw_entry in entries:
        entry = mapping(raw_entry, field="facebook.entry[]")
        entry_id = provider_id(entry.get("id"), field="facebook.entry.id")
        changes = list_value(entry.get("changes"), field="facebook.entry.changes")
        for raw_change in changes:
            change = mapping(raw_change, field="facebook.entry.changes[]")
            normalized, was_ignored = _normalize_facebook(entry_id=entry_id, change=change)
            if normalized is not None:
                events.append(normalized)
            ignored += int(was_ignored)
    return events, ignored


def _instagram_changes(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Support both documented direct field/value and batched changes envelopes."""

    if "changes" in entry:
        return [
            mapping(value, field="instagram.entry.changes[]")
            for value in list_value(entry.get("changes"), field="instagram.entry.changes")
        ]
    if "field" in entry or "value" in entry:
        return [entry]
    raise IngressPayloadError("instagram entry contains no change envelope")


def _normalize_instagram(
    *,
    entry_id: str,
    change: dict[str, Any],
) -> tuple[NormalizedInboundEvent | None, bool]:
    if change.get("field") != "comments":
        return None, True
    value = mapping(change.get("value"), field="instagram.change.value")
    if "text" not in value:
        return None, True

    author = mapping(value.get("from"), field="instagram.change.value.from")
    author_id = provider_id(author.get("id"), field="instagram.author_id")
    if author_id == entry_id:
        return None, True
    media = mapping(value.get("media"), field="instagram.change.value.media")

    try:
        normalized = InstagramAdapter.normalize(
            InstagramCommentDTO(
                comment_id=provider_id(value.get("id"), field="instagram.comment_id"),
                media_id=provider_id(media.get("id"), field="instagram.media_id"),
                author_id=author_id,
                text=provider_text(value.get("text"), field="instagram.text"),
            )
        )
    except ValueError as exc:
        raise IngressPayloadError(str(exc)) from None
    return normalized, False


def _instagram_events(payload: dict[str, Any]) -> tuple[list[NormalizedInboundEvent], int]:
    entries = list_value(payload.get("entry"), field="instagram.entry")
    events: list[NormalizedInboundEvent] = []
    ignored = 0
    for raw_entry in entries:
        entry = mapping(raw_entry, field="instagram.entry[]")
        entry_id = provider_id(entry.get("id"), field="instagram.entry.id")
        for change in _instagram_changes(entry):
            normalized, was_ignored = _normalize_instagram(entry_id=entry_id, change=change)
            if normalized is not None:
                events.append(normalized)
            ignored += int(was_ignored)
    return events, ignored


class MetaWebhookIngress:
    """Authenticate raw Meta bytes, decode supported comments, then persist normalized events."""

    def __init__(self, *, collector: ExactIngestionCollector, app_secret: str) -> None:
        if not isinstance(app_secret, str) or not app_secret:
            raise ValueError("Meta app secret must not be empty")
        self._collector = collector
        self._app_secret = app_secret

    def ingest(self, *, raw_body: bytes, signature_header: str) -> IngressBatchResult:
        body = validate_raw_body(raw_body)
        verify_meta_signature(
            raw_body=body,
            signature_header=signature_header,
            app_secret=self._app_secret,
        )
        payload = load_json_object(body)

        object_type = payload.get("object")
        if object_type == "page":
            events, ignored = _facebook_events(payload)
        elif object_type == "instagram":
            events, ignored = _instagram_events(payload)
        else:
            raise UnsupportedIngressEvent("unsupported Meta webhook object")

        results = tuple(self._collector.ingest(event) for event in events)
        return IngressBatchResult(results=results, ignored_count=ignored)
