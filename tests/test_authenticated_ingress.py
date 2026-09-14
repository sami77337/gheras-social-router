from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.platforms.live_security import WebhookVerificationError
from app.api.integrations import IngressRuntime, build_ingress_router
from app.ingress.common import (
    ExactIngestionCollector,
    IngressConflict,
    IngressPayloadError,
)
from app.ingress.meta import MetaWebhookIngress
from app.ingress.telegram import TelegramWebhookIngress
from app.ingress.youtube import YouTubePollingIngress
from app.main import create_app
from app.persistence.repositories import DurableRepository
from app.persistence.sqlite import SQLiteDatabase
from app.services.ingestion import IngestionService

META_SECRET = "phase13-meta-secret"
META_VERIFY_TOKEN = "phase13-meta-verify"
TELEGRAM_SECRET = "Phase13_Telegram-Secret"


def _services(
    tmp_path: Path,
) -> tuple[ExactIngestionCollector, DurableRepository, Path]:
    database_path = tmp_path / "router.db"
    database = SQLiteDatabase(database_path)
    database.initialize()
    repository = DurableRepository(database)
    collector = ExactIngestionCollector(IngestionService(repository))
    return collector, repository, database_path


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _meta_signature(raw_body: bytes) -> str:
    digest = hmac.new(META_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _facebook_payload(*, text: str = "السلام عليكم") -> dict[str, Any]:
    return {
        "object": "page",
        "entry": [
            {
                "id": "page-1",
                "time": 1770000000,
                "changes": [
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": "add",
                            "comment_id": "fb-comment-1",
                            "post_id": "fb-post-1",
                            "from": {"id": "fb-user-1", "name": "ignored-name"},
                            "message": text,
                            "private_secret_marker": "RAW_PAYLOAD_MUST_NOT_PERSIST",
                        },
                    }
                ],
            }
        ],
    }


def _telegram_payload(*, text: str = "مرحبا", is_bot: bool = False) -> dict[str, Any]:
    return {
        "update_id": 100,
        "message": {
            "message_id": 55,
            "from": {"id": 42, "is_bot": is_bot, "first_name": "ignored"},
            "chat": {"id": -777, "type": "private"},
            "date": 1770000000,
            "text": text,
            "private_secret_marker": "TELEGRAM_RAW_MUST_NOT_PERSIST",
        },
    }


def test_meta_authentication_runs_before_json_parse(tmp_path: Path) -> None:
    collector, _, _ = _services(tmp_path)
    ingress = MetaWebhookIngress(collector=collector, app_secret=META_SECRET)

    with pytest.raises(WebhookVerificationError, match="mismatch"):
        ingress.ingest(
            raw_body=b"{definitely-not-json",
            signature_header="sha256=" + "0" * 64,
        )


def test_telegram_authentication_runs_before_json_parse(tmp_path: Path) -> None:
    collector, _, _ = _services(tmp_path)
    ingress = TelegramWebhookIngress(
        collector=collector,
        webhook_secret=TELEGRAM_SECRET,
    )

    with pytest.raises(WebhookVerificationError, match="mismatch"):
        ingress.ingest(raw_body=b"{not-json", secret_header="wrong-secret")


def test_authenticated_facebook_comment_is_persisted_once_without_raw_payload(
    tmp_path: Path,
) -> None:
    collector, repository, database_path = _services(tmp_path)
    ingress = MetaWebhookIngress(collector=collector, app_secret=META_SECRET)
    raw = _json_bytes(_facebook_payload(text="السلام عليكم، متى يبدأ التسجيل؟"))

    first = ingress.ingest(raw_body=raw, signature_header=_meta_signature(raw))
    duplicate = ingress.ingest(raw_body=raw, signature_header=_meta_signature(raw))

    assert first.accepted_count == 1
    assert first.created_count == 1
    assert duplicate.accepted_count == 1
    assert duplicate.duplicate_count == 1
    assert repository.count_events() == 1

    event = first.results[0].event
    assert event.external_comment_id == "fb-comment-1"
    assert event.external_post_id == "fb-post-1"
    assert event.author_id == "fb-user-1"
    assert event.text == "السلام عليكم، متى يبدأ التسجيل؟"
    assert event.media is None
    assert b"RAW_PAYLOAD_MUST_NOT_PERSIST" not in database_path.read_bytes()


def test_same_facebook_identity_with_changed_semantics_fails_closed(tmp_path: Path) -> None:
    collector, repository, _ = _services(tmp_path)
    ingress = MetaWebhookIngress(collector=collector, app_secret=META_SECRET)
    first_raw = _json_bytes(_facebook_payload(text="النص الأصلي"))
    changed_raw = _json_bytes(_facebook_payload(text="نص مختلف"))

    ingress.ingest(raw_body=first_raw, signature_header=_meta_signature(first_raw))
    with pytest.raises(IngressConflict, match="conflicts"):
        ingress.ingest(
            raw_body=changed_raw,
            signature_header=_meta_signature(changed_raw),
        )

    assert repository.count_events() == 1
    stored = repository.get_event(
        ingress.ingest(
            raw_body=first_raw,
            signature_header=_meta_signature(first_raw),
        ).results[0].event.id
    )
    assert stored.text == "النص الأصلي"


def test_meta_rejects_duplicate_json_object_keys_after_authentication(tmp_path: Path) -> None:
    collector, _, _ = _services(tmp_path)
    ingress = MetaWebhookIngress(collector=collector, app_secret=META_SECRET)
    raw = b'{"object":"page","object":"instagram","entry":[]}'

    with pytest.raises(IngressPayloadError, match="duplicate keys"):
        ingress.ingest(raw_body=raw, signature_header=_meta_signature(raw))


def test_instagram_comments_support_current_direct_field_envelope(tmp_path: Path) -> None:
    collector, repository, _ = _services(tmp_path)
    ingress = MetaWebhookIngress(collector=collector, app_secret=META_SECRET)
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "ig-owner-1",
                "time": 1770000000,
                "field": "comments",
                "value": {
                    "id": "ig-comment-1",
                    "from": {"id": "ig-user-1", "username": "ignored"},
                    "text": "تعليق إنستغرام كما هو",
                    "media": {"id": "ig-media-1", "media_product_type": "REELS"},
                },
            }
        ],
    }
    raw = _json_bytes(payload)

    batch = ingress.ingest(raw_body=raw, signature_header=_meta_signature(raw))

    assert batch.created_count == 1
    assert repository.count_events() == 1
    event = batch.results[0].event
    assert event.external_comment_id == "ig-comment-1"
    assert event.external_post_id == "ig-media-1"
    assert event.author_id == "ig-user-1"
    assert event.text == "تعليق إنستغرام كما هو"


def test_instagram_comments_support_changes_envelope_and_ignore_self_comment(
    tmp_path: Path,
) -> None:
    collector, repository, _ = _services(tmp_path)
    ingress = MetaWebhookIngress(collector=collector, app_secret=META_SECRET)
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "ig-owner-1",
                "changes": [
                    {
                        "field": "comments",
                        "value": {
                            "id": "ig-comment-self",
                            "from": {"id": "ig-owner-1"},
                            "text": "رد الحساب نفسه",
                            "media": {"id": "ig-media-1"},
                        },
                    }
                ],
            }
        ],
    }
    raw = _json_bytes(payload)

    batch = ingress.ingest(raw_body=raw, signature_header=_meta_signature(raw))

    assert batch.accepted_count == 0
    assert batch.ignored_count == 1
    assert repository.count_events() == 0


def test_authenticated_telegram_message_preserves_identity_and_text(tmp_path: Path) -> None:
    collector, repository, database_path = _services(tmp_path)
    ingress = TelegramWebhookIngress(
        collector=collector,
        webhook_secret=TELEGRAM_SECRET,
    )
    raw = _json_bytes(_telegram_payload(text="رسالة تيليجرام كما هي"))

    first = ingress.ingest(raw_body=raw, secret_header=TELEGRAM_SECRET)
    duplicate = ingress.ingest(raw_body=raw, secret_header=TELEGRAM_SECRET)

    assert first.created_count == 1
    assert duplicate.duplicate_count == 1
    assert repository.count_events() == 1
    event = first.results[0].event
    assert event.external_event_key == "-777:55"
    assert event.external_event_id == "100"
    assert event.author_id == "42"
    assert event.text == "رسالة تيليجرام كما هي"
    assert b"TELEGRAM_RAW_MUST_NOT_PERSIST" not in database_path.read_bytes()


def test_telegram_bot_authored_message_is_ignored(tmp_path: Path) -> None:
    collector, repository, _ = _services(tmp_path)
    ingress = TelegramWebhookIngress(
        collector=collector,
        webhook_secret=TELEGRAM_SECRET,
    )
    raw = _json_bytes(_telegram_payload(is_bot=True))

    batch = ingress.ingest(raw_body=raw, secret_header=TELEGRAM_SECRET)

    assert batch.accepted_count == 0
    assert batch.ignored_count == 1
    assert repository.count_events() == 0


class FakeYouTubeSource:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str | None, int | None]] = []

    async def list_comment_threads(
        self,
        *,
        video_id: str,
        page_token: str | None = None,
        max_results: int | None = None,
    ) -> Mapping[str, Any]:
        self.calls.append((video_id, page_token, max_results))
        return self.payload


def _youtube_item(
    *,
    text_display: str,
    text_original: str | None = None,
    author_id: str = "yt-user-1",
    video_id: str = "yt-video-1",
) -> dict[str, Any]:
    snippet: dict[str, Any] = {
        "authorChannelId": {"value": author_id},
        "textDisplay": text_display,
    }
    if text_original is not None:
        snippet["textOriginal"] = text_original
    return {
        "id": "yt-thread-1",
        "snippet": {
            "videoId": video_id,
            "topLevelComment": {
                "id": "yt-comment-1",
                "snippet": snippet,
            },
        },
    }


def test_youtube_poll_uses_provider_original_when_available(tmp_path: Path) -> None:
    collector, repository, _ = _services(tmp_path)
    source = FakeYouTubeSource(
        {
            "items": [
                _youtube_item(
                    text_display="display representation",
                    text_original="النص الأصلي من المزود",
                )
            ],
            "nextPageToken": "next-page",
        }
    )
    ingress = YouTubePollingIngress(
        source=source,
        collector=collector,
        own_channel_id="yt-owner",
    )

    result = asyncio.run(
        ingress.poll_video(
            video_id="yt-video-1",
            page_token="page-1",
            max_results=25,
        )
    )

    assert result.batch.created_count == 1
    assert result.next_page_token == "next-page"
    assert source.calls == [("yt-video-1", "page-1", 25)]
    assert repository.count_events() == 1
    assert result.batch.results[0].event.text == "النص الأصلي من المزود"


def test_youtube_poll_falls_back_to_plain_text_display_and_ignores_self(tmp_path: Path) -> None:
    collector, repository, _ = _services(tmp_path)
    source = FakeYouTubeSource(
        {
            "items": [
                _youtube_item(text_display="تعليق متاح بصيغة العرض"),
                {
                    **_youtube_item(
                        text_display="تعليق الحساب نفسه",
                        author_id="yt-owner",
                    ),
                    "id": "yt-thread-self",
                },
            ]
        }
    )
    ingress = YouTubePollingIngress(
        source=source,
        collector=collector,
        own_channel_id="yt-owner",
    )

    result = asyncio.run(ingress.poll_video(video_id="yt-video-1"))

    assert result.batch.created_count == 1
    assert result.batch.ignored_count == 1
    assert repository.count_events() == 1
    assert result.batch.results[0].event.text == "تعليق متاح بصيغة العرض"


def test_youtube_cross_video_payload_fails_closed(tmp_path: Path) -> None:
    collector, repository, _ = _services(tmp_path)
    source = FakeYouTubeSource(
        {"items": [_youtube_item(text_display="text", video_id="wrong-video")]}
    )
    ingress = YouTubePollingIngress(
        source=source,
        collector=collector,
        own_channel_id="yt-owner",
    )

    with pytest.raises(IngressPayloadError, match="does not match"):
        asyncio.run(ingress.poll_video(video_id="yt-video-1"))
    assert repository.count_events() == 0


def test_default_application_does_not_mount_provider_ingress_routes() -> None:
    paths = {
        path
        for route in create_app().routes
        if isinstance((path := getattr(route, "path", None)), str)
    }
    assert "/integrations/meta/webhook" not in paths
    assert "/integrations/telegram/webhook" not in paths


def test_explicit_router_supports_meta_handshake_and_authenticated_ingress(
    tmp_path: Path,
) -> None:
    collector, repository, _ = _services(tmp_path)
    runtime = IngressRuntime(
        meta=MetaWebhookIngress(collector=collector, app_secret=META_SECRET),
        telegram=TelegramWebhookIngress(
            collector=collector,
            webhook_secret=TELEGRAM_SECRET,
        ),
        meta_verify_token=META_VERIFY_TOKEN,
    )
    app = FastAPI()
    app.include_router(build_ingress_router(runtime))
    client = TestClient(app)

    verify = client.get(
        "/integrations/meta/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": META_VERIFY_TOKEN,
            "hub.challenge": "123456",
        },
    )
    assert verify.status_code == 200
    assert verify.text == "123456"

    raw = _json_bytes(_facebook_payload())
    response = client.post(
        "/integrations/meta/webhook",
        content=raw,
        headers={
            "content-type": "application/json",
            "x-hub-signature-256": _meta_signature(raw),
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "accepted": 1,
        "created": 1,
        "duplicates": 0,
        "ignored": 0,
    }
    assert repository.count_events() == 1


def test_explicit_router_returns_generic_auth_error_without_parsing_body(
    tmp_path: Path,
) -> None:
    collector, _, _ = _services(tmp_path)
    runtime = IngressRuntime(
        meta=MetaWebhookIngress(collector=collector, app_secret=META_SECRET),
        telegram=TelegramWebhookIngress(
            collector=collector,
            webhook_secret=TELEGRAM_SECRET,
        ),
        meta_verify_token=META_VERIFY_TOKEN,
    )
    app = FastAPI()
    app.include_router(build_ingress_router(runtime))
    client = TestClient(app)

    response = client.post(
        "/integrations/meta/webhook",
        content=b"{malformed-json",
        headers={
            "content-type": "application/json",
            "x-hub-signature-256": "sha256=" + "0" * 64,
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "invalid webhook authentication"}


def test_explicit_router_rejects_non_json_content_type(tmp_path: Path) -> None:
    collector, _, _ = _services(tmp_path)
    runtime = IngressRuntime(
        meta=MetaWebhookIngress(collector=collector, app_secret=META_SECRET),
        telegram=TelegramWebhookIngress(
            collector=collector,
            webhook_secret=TELEGRAM_SECRET,
        ),
        meta_verify_token=META_VERIFY_TOKEN,
    )
    app = FastAPI()
    app.include_router(build_ingress_router(runtime))
    client = TestClient(app)

    response = client.post(
        "/integrations/telegram/webhook",
        content=b"{}",
        headers={
            "content-type": "text/plain",
            "x-telegram-bot-api-secret-token": TELEGRAM_SECRET,
        },
    )

    assert response.status_code == 415
