from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from app.adapters.platforms.common import AdapterPayloadError
from app.adapters.platforms.facebook import (
    FacebookAdapter,
    FacebookCommentDTO,
    FacebookReplyPublisher,
)
from app.adapters.platforms.instagram import (
    InstagramAdapter,
    InstagramCommentDTO,
    InstagramReplyPublisher,
)
from app.adapters.platforms.telegram import (
    TelegramAdapter,
    TelegramMessageDTO,
    TelegramReplyPublisher,
    TelegramSupervisorTransport,
)
from app.adapters.platforms.youtube import (
    YouTubeAdapter,
    YouTubeCommentDTO,
    YouTubeReplyPublisher,
)
from app.domain.events import Platform
from app.domain.supervisor import SupervisorDispatchRequest
from app.persistence.repositories import DurableRepository
from app.persistence.sqlite import SQLiteDatabase
from app.services.ingestion import IngestionService


class FakeCommentClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def reply_to_comment(self, comment_id: str, text: str) -> str:
        self.calls.append((comment_id, text))
        return f"reply-{comment_id}"


class FakeTelegramReplyClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def reply_to_message(self, target_id: str, text: str) -> str:
        self.calls.append((target_id, text))
        return "telegram-reply-1"


class FakeSupervisorClient:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_supervisor_message(self, text: str) -> str:
        self.messages.append(text)
        return "telegram-thread-1"


def test_facebook_normalization_preserves_arabic_text() -> None:
    text = "السلام عليكم، متى يبدأ التسجيل؟"
    event = FacebookAdapter.normalize(
        FacebookCommentDTO(
            comment_id="fb-comment-1",
            post_id="fb-post-1",
            author_id="fb-user-1",
            text=text,
            event_id="fb-delivery-9",
        )
    )

    assert event.platform is Platform.FACEBOOK
    assert event.external_event_key == "fb-comment-1"
    assert event.external_event_id == "fb-delivery-9"
    assert event.external_comment_id == "fb-comment-1"
    assert event.external_post_id == "fb-post-1"
    assert event.text == text


def test_instagram_normalization_uses_comment_as_stable_event_key() -> None:
    event = InstagramAdapter.normalize(
        InstagramCommentDTO(
            comment_id="ig-comment-1",
            media_id="ig-media-1",
            author_id="ig-user-1",
            text="تعليق إنستغرام",
            event_id="ig-delivery-1",
        )
    )

    assert event.platform is Platform.INSTAGRAM
    assert event.external_event_key == "ig-comment-1"
    assert event.external_post_id == "ig-media-1"


def test_telegram_redelivery_collapses_on_chat_and_message_identity() -> None:
    first = TelegramAdapter.normalize(
        TelegramMessageDTO(
            update_id="100",
            message_id="55",
            chat_id="777",
            author_id="42",
            text="مرحبا",
        )
    )
    redelivery = TelegramAdapter.normalize(
        TelegramMessageDTO(
            update_id="101",
            message_id="55",
            chat_id="777",
            author_id="42",
            text="مرحبا",
        )
    )

    assert first.external_event_key == "777:55"
    assert redelivery.external_event_key == first.external_event_key
    assert first.external_event_id == "100"
    assert redelivery.external_event_id == "101"


def test_youtube_normalization_preserves_video_and_thread_identity() -> None:
    event = YouTubeAdapter.normalize(
        YouTubeCommentDTO(
            comment_id="yt-comment-1",
            video_id="yt-video-1",
            author_channel_id="yt-channel-1",
            text="تعليق يوتيوب",
            thread_id="yt-thread-1",
        )
    )

    assert event.platform is Platform.YOUTUBE
    assert event.external_event_key == "yt-comment-1"
    assert event.external_event_id == "yt-thread-1"
    assert event.external_post_id == "yt-video-1"


@pytest.mark.parametrize(
    ("normalizer", "dto"),
    [
        (
            FacebookAdapter.normalize,
            FacebookCommentDTO(" ", "post", "author", "text"),
        ),
        (
            InstagramAdapter.normalize,
            InstagramCommentDTO("comment", " ", "author", "text"),
        ),
        (
            TelegramAdapter.normalize,
            TelegramMessageDTO("1", " ", "chat", "author", "text"),
        ),
        (
            YouTubeAdapter.normalize,
            YouTubeCommentDTO("comment", "video", " ", "text"),
        ),
    ],
)
def test_malformed_required_identifiers_fail_closed(normalizer: object, dto: object) -> None:
    with pytest.raises(AdapterPayloadError):
        normalizer(dto)  # type: ignore[operator]


def test_empty_provider_text_fails_closed() -> None:
    with pytest.raises(AdapterPayloadError, match="text"):
        FacebookAdapter.normalize(
            FacebookCommentDTO("comment", "post", "author", "   ")
        )


def test_normalized_duplicate_is_idempotent_in_durable_core(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()
    ingestion = IngestionService(DurableRepository(database))

    first = FacebookAdapter.normalize(
        FacebookCommentDTO(
            "same-comment",
            "post-1",
            "author-1",
            "نفس التعليق",
            event_id="delivery-1",
        )
    )
    duplicate = FacebookAdapter.normalize(
        FacebookCommentDTO(
            "same-comment",
            "post-1",
            "author-1",
            "نفس التعليق",
            event_id="delivery-2",
        )
    )

    stored_first = ingestion.ingest_event(first)
    stored_duplicate = ingestion.ingest_event(duplicate)

    assert stored_first.created is True
    assert stored_duplicate.created is False
    assert stored_first.event.id == stored_duplicate.event.id


def test_facebook_and_instagram_publishers_delegate_only_to_injected_clients() -> None:
    facebook_client = FakeCommentClient()
    instagram_client = FakeCommentClient()

    facebook_id = asyncio.run(
        FacebookReplyPublisher(facebook_client).publish_reply(
            external_comment_id="fb-1",
            text="رد فيسبوك",
        )
    )
    instagram_id = asyncio.run(
        InstagramReplyPublisher(instagram_client).publish_reply(
            external_comment_id="ig-1",
            text="رد إنستغرام",
        )
    )

    assert facebook_id == "reply-fb-1"
    assert instagram_id == "reply-ig-1"
    assert facebook_client.calls == [("fb-1", "رد فيسبوك")]
    assert instagram_client.calls == [("ig-1", "رد إنستغرام")]


def test_telegram_reply_publisher_delegates_to_injected_client() -> None:
    client = FakeTelegramReplyClient()

    result = asyncio.run(
        TelegramReplyPublisher(client).publish_reply(
            external_comment_id="777:55",
            text="رد تيليجرام",
        )
    )

    assert result == "telegram-reply-1"
    assert client.calls == [("777:55", "رد تيليجرام")]


def test_youtube_reply_publisher_delegates_to_injected_client() -> None:
    client = FakeCommentClient()

    result = asyncio.run(
        YouTubeReplyPublisher(client).publish_reply(
            external_comment_id="yt-comment-1",
            text="رد يوتيوب",
        )
    )

    assert result == "reply-yt-comment-1"
    assert client.calls == [("yt-comment-1", "رد يوتيوب")]


def test_telegram_supervisor_transport_uses_minimal_plain_text_payload() -> None:
    client = FakeSupervisorClient()
    request = SupervisorDispatchRequest(
        escalation_id="esc-1",
        event_id="event-1",
        platform="youtube",
        text="أحتاج مراجعة بشرية",
        correlation_id="corr-1",
    )

    result = asyncio.run(TelegramSupervisorTransport(client).dispatch(request))

    assert result == "telegram-thread-1"
    assert len(client.messages) == 1
    message = client.messages[0]
    assert "escalation_id=esc-1" in message
    assert "event_id=event-1" in message
    assert "platform=youtube" in message
    assert "text=أحتاج مراجعة بشرية" in message


def test_provider_modules_do_not_embed_network_clients() -> None:
    modules = [
        FacebookAdapter,
        InstagramAdapter,
        TelegramAdapter,
        YouTubeAdapter,
    ]
    forbidden = ("httpx", "requests", "aiohttp", "graph.facebook.com", "googleapis.com")

    for adapter in modules:
        source = inspect.getsource(inspect.getmodule(adapter))
        assert not any(value in source for value in forbidden)
