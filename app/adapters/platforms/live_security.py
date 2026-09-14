"""Pure provider security helpers for future sandbox/live integration.

No network client or provider SDK is allowed in this module. Verification must
run on raw provider evidence before any semantic routing or side effect.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from enum import StrEnum

from app.adapters.platforms.common import AdapterPayloadError


class WebhookVerificationError(AdapterPayloadError):
    """Raised when provider webhook evidence cannot be authenticated."""


class YouTubeIngestionMode(StrEnum):
    """Supported YouTube comment-ingestion mechanism for the prepared adapter."""

    POLL_COMMENT_THREADS = "poll_comment_threads"


_META_VERSION_PATTERN = re.compile(r"^v[1-9][0-9]*\.[0-9]+$")


def validate_meta_graph_api_version(value: str) -> str:
    """Accept only a compact Meta Graph API version such as ``v26.0``."""

    if not isinstance(value, str) or not _META_VERSION_PATTERN.fullmatch(value):
        raise WebhookVerificationError("invalid Meta Graph API version")
    if len(value) > 16:
        raise WebhookVerificationError("Meta Graph API version is too long")
    return value


def _required_secret(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise WebhookVerificationError(f"{field} must be a string")
    if not value:
        raise WebhookVerificationError(f"{field} must not be empty")
    return value


def verify_meta_handshake(
    *,
    mode: str,
    verify_token: str,
    challenge: str,
    expected_verify_token: str,
) -> str:
    """Validate Meta's subscription handshake and echo the challenge verbatim."""

    expected = _required_secret(expected_verify_token, field="expected_verify_token")
    if mode != "subscribe":
        raise WebhookVerificationError("unsupported Meta webhook mode")
    if not hmac.compare_digest(verify_token, expected):
        raise WebhookVerificationError("Meta verify token mismatch")
    if not isinstance(challenge, str) or not challenge:
        raise WebhookVerificationError("Meta challenge must not be empty")
    return challenge


def verify_meta_signature(
    *,
    raw_body: bytes,
    signature_header: str,
    app_secret: str,
) -> None:
    """Authenticate a Meta webhook using HMAC-SHA256 over the raw body."""

    secret = _required_secret(app_secret, field="app_secret")
    if not isinstance(raw_body, bytes):
        raise WebhookVerificationError("raw_body must be bytes")
    if not isinstance(signature_header, str) or not signature_header.startswith("sha256="):
        raise WebhookVerificationError("invalid Meta signature header")

    supplied = signature_header.removeprefix("sha256=")
    if len(supplied) != 64:
        raise WebhookVerificationError("invalid Meta signature length")
    try:
        int(supplied, 16)
    except ValueError as exc:
        raise WebhookVerificationError("invalid Meta signature encoding") from exc

    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied.lower(), expected):
        raise WebhookVerificationError("Meta signature mismatch")


_TELEGRAM_SECRET_ALLOWED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)


def validate_telegram_webhook_secret(secret: str) -> str:
    """Validate Telegram's documented webhook secret-token character contract."""

    value = _required_secret(secret, field="telegram_webhook_secret")
    if not 1 <= len(value) <= 256:
        raise WebhookVerificationError("Telegram webhook secret length is invalid")
    if any(char not in _TELEGRAM_SECRET_ALLOWED for char in value):
        raise WebhookVerificationError("Telegram webhook secret contains invalid characters")
    return value


def verify_telegram_webhook_secret(*, supplied_header: str, expected_secret: str) -> None:
    """Authenticate Telegram webhook delivery using constant-time comparison."""

    expected = validate_telegram_webhook_secret(expected_secret)
    if not isinstance(supplied_header, str):
        raise WebhookVerificationError("Telegram webhook header must be a string")
    if not hmac.compare_digest(supplied_header, expected):
        raise WebhookVerificationError("Telegram webhook secret mismatch")


@dataclass(frozen=True, slots=True)
class YouTubePollingPolicy:
    """Current provider-contract snapshot for comment polling and reply budgeting."""

    ingestion_mode: YouTubeIngestionMode = YouTubeIngestionMode.POLL_COMMENT_THREADS
    max_results_per_page: int = 100
    comment_list_quota_units: int = 1
    reply_insert_quota_units: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.max_results_per_page <= 100:
            raise ValueError("YouTube max_results_per_page must be between 1 and 100")
        if self.comment_list_quota_units <= 0:
            raise ValueError("YouTube comment-list quota units must be positive")
        if self.reply_insert_quota_units <= 0:
            raise ValueError("YouTube reply-insert quota units must be positive")
