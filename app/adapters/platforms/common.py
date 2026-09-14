"""Shared validation helpers for mock-first provider adapters."""

from __future__ import annotations

_MAX_PROVIDER_ID = 512
_MAX_REPLY_TEXT = 10000


class AdapterPayloadError(ValueError):
    """Raised when provider data cannot be normalized without guessing."""


def required_id(value: str, *, field: str) -> str:
    """Validate one stable provider identifier without rewriting it."""

    if not isinstance(value, str):
        raise AdapterPayloadError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise AdapterPayloadError(f"{field} must not be empty")
    if len(normalized) > _MAX_PROVIDER_ID:
        raise AdapterPayloadError(f"{field} exceeds maximum identifier length")
    if any(char.isspace() for char in normalized):
        raise AdapterPayloadError(f"{field} must not contain whitespace")
    return normalized


def optional_id(value: str | None, *, field: str) -> str | None:
    """Validate an optional provider identifier."""

    if value is None:
        return None
    return required_id(value, field=field)


def required_text(value: str, *, field: str = "text") -> str:
    """Require non-empty text while preserving the provider text verbatim."""

    if not isinstance(value, str):
        raise AdapterPayloadError(f"{field} must be a string")
    if not value.strip():
        raise AdapterPayloadError(f"{field} must not be empty")
    return value


def reply_text(value: str) -> str:
    """Validate outbound text without semantic rewriting."""

    text = required_text(value, field="reply_text")
    if len(text) > _MAX_REPLY_TEXT:
        raise AdapterPayloadError("reply_text exceeds safe adapter boundary")
    return text
