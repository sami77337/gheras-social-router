"""Shared fail-closed helpers for authenticated inbound provider data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.adapters.platforms.common import required_id, required_text
from app.domain.events import InboundEvent, IngestionResult, NormalizedInboundEvent
from app.services.ingestion import IngestionService

MAX_WEBHOOK_BODY_BYTES = 1_000_000


class IngressPayloadError(ValueError):
    """Raised when authenticated provider input cannot be decoded safely."""


class UnsupportedIngressEvent(IngressPayloadError):
    """Raised when a provider object is outside the V1 ingress contract."""


class IngressConflict(RuntimeError):
    """Raised when one stable provider identity is reused with changed semantics."""


@dataclass(frozen=True, slots=True)
class IngressBatchResult:
    """Redaction-safe batch result; no provider payload or user text is exposed."""

    results: tuple[IngestionResult, ...]
    ignored_count: int = 0

    @property
    def accepted_count(self) -> int:
        return len(self.results)

    @property
    def created_count(self) -> int:
        return sum(result.created for result in self.results)

    @property
    def duplicate_count(self) -> int:
        return self.accepted_count - self.created_count


def validate_raw_body(raw_body: bytes) -> bytes:
    """Bound one raw webhook body before authentication or parsing work."""

    if not isinstance(raw_body, bytes):
        raise IngressPayloadError("webhook body must be bytes")
    if not raw_body:
        raise IngressPayloadError("webhook body must not be empty")
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise IngressPayloadError("webhook body exceeds maximum size")
    return raw_body


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IngressPayloadError("JSON object contains duplicate keys")
        result[key] = value
    return result


def load_json_object(raw_body: bytes) -> dict[str, Any]:
    """Decode bounded UTF-8 JSON while rejecting duplicate object keys."""

    body = validate_raw_body(raw_body)
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise IngressPayloadError("webhook body must be UTF-8 JSON") from None
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except IngressPayloadError:
        raise
    except (json.JSONDecodeError, RecursionError):
        raise IngressPayloadError("webhook body is not valid bounded JSON") from None
    if not isinstance(payload, dict):
        raise IngressPayloadError("webhook JSON must be an object")
    return payload


def mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IngressPayloadError(f"{field} must be an object")
    return value


def list_value(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise IngressPayloadError(f"{field} must be a list")
    return value


def provider_id(value: Any, *, field: str) -> str:
    """Preserve string ids and losslessly normalize integer JSON ids to decimal text."""

    if isinstance(value, bool):
        raise IngressPayloadError(f"{field} must be an identifier")
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        raise IngressPayloadError(f"{field} must be a string or integer")
    try:
        return required_id(value, field=field)
    except ValueError as exc:
        raise IngressPayloadError(str(exc)) from None


def provider_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise IngressPayloadError(f"{field} must be a string")
    try:
        return required_text(value, field=field)
    except ValueError as exc:
        raise IngressPayloadError(str(exc)) from None


def _same_semantics(stored: InboundEvent, proposed: NormalizedInboundEvent) -> bool:
    """Compare immutable semantics while excluding delivery-only external_event_id."""

    return (
        stored.platform is proposed.platform
        and stored.external_event_key == proposed.external_event_key
        and stored.external_comment_id == proposed.external_comment_id
        and stored.external_post_id == proposed.external_post_id
        and stored.author_id == proposed.author_id
        and stored.text == proposed.text
        and stored.media == proposed.media
    )


class ExactIngestionCollector:
    """Persist normalized events and reject semantic collisions on duplicate identities."""

    def __init__(self, ingestion: IngestionService) -> None:
        self.ingestion = ingestion

    def ingest(self, event: NormalizedInboundEvent) -> IngestionResult:
        result = self.ingestion.ingest_event(event)
        if not result.created and not _same_semantics(result.event, event):
            raise IngressConflict("provider event identity conflicts with durable semantics")
        return result
