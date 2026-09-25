from __future__ import annotations

import asyncio
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from app.acquisition.common import (
    AcquisitionLimitExceeded,
    AcquisitionProtocolError,
    merge_replay_corpora,
    write_replay_jsonl,
)
from app.acquisition.telegram_export import load_telegram_desktop_export
from app.domain.events import Platform
from app.integrations.live.activation import (
    ExternalIntegrationDisabled,
    issue_sandbox_execution_permit,
)
from app.integrations.live.historical_meta import MetaHistoricalCommentClient
from app.integrations.live.historical_youtube import YouTubeHistoricalCommentClient
from app.operations.replay import load_replay_corpus


def _permit():
    return issue_sandbox_execution_permit(purpose="sandbox_validation")


def test_telegram_html_zip_import_redacts_senders_and_writes_replay(tmp_path: Path) -> None:
    export = tmp_path / "telegram-export.zip"
    html = """
    <html><body>
      <div class="message service" id="service1"><div class="text">joined</div></div>
      <div class="message default clearfix" id="message10">
        <div class="from_name">Private Person</div>
        <div class="text">First<br>message</div>
      </div>
      <div class="message default clearfix" id="message11">
        <div class="text">Second message</div>
      </div>
    </body></html>
    """
    with zipfile.ZipFile(export, "w") as archive:
        archive.writestr("ChatExport/messages.html", html)

    batch = load_telegram_desktop_export(export)
    assert batch.platform is Platform.TELEGRAM
    assert batch.record_count == 2
    assert "Private Person" not in repr(batch.comments)
    assert all(comment.platform is Platform.TELEGRAM for comment in batch.comments)

    output = tmp_path / "telegram.replay.jsonl"
    manifest = write_replay_jsonl(output, batch.comments)
    corpus = load_replay_corpus(output)
    assert manifest["record_count"] == 2
    assert corpus.manifest.by_platform == {"telegram": 2}
    assert all(record.author_id is None for record in corpus.records)


def test_youtube_channel_reader_uses_get_only_and_collects_all_replies() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "www.googleapis.com"
        if request.url.path.endswith("/commentThreads"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "thread-1",
                            "snippet": {
                                "videoId": "video-1",
                                "totalReplyCount": 2,
                                "topLevelComment": {
                                    "id": "top-1",
                                    "snippet": {"textOriginal": "Top comment"},
                                },
                            },
                            "replies": {
                                "comments": [
                                    {
                                        "id": "reply-1",
                                        "snippet": {"textOriginal": "Inline reply"},
                                    }
                                ]
                            },
                        }
                    ]
                },
            )
        if request.url.path.endswith("/comments"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "reply-1",
                            "snippet": {"textOriginal": "Inline reply"},
                        },
                        {
                            "id": "reply-2",
                            "snippet": {"textOriginal": "Second reply"},
                        },
                    ]
                },
            )
        raise AssertionError("unexpected YouTube path")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = YouTubeHistoricalCommentClient(
                http=http,
                permit=_permit(),
                api_key="test-api-key",
            )
            return await client.collect_channel("channel-1")

    batch = asyncio.run(run())
    assert batch.platform is Platform.YOUTUBE
    assert batch.record_count == 3
    assert {comment.comment_id for comment in batch.comments} == {
        "top-1",
        "reply-1",
        "reply-2",
    }
    assert all(comment.source_id == "video-1" for comment in batch.comments)
    assert len(requests) == 2



def test_youtube_conflicting_duplicate_reply_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/commentThreads"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "thread-conflict",
                            "snippet": {
                                "videoId": "video-conflict",
                                "totalReplyCount": 2,
                                "topLevelComment": {
                                    "id": "top-conflict",
                                    "snippet": {"textOriginal": "Top"},
                                },
                            },
                            "replies": {
                                "comments": [
                                    {
                                        "id": "reply-conflict",
                                        "snippet": {"textOriginal": "first snapshot"},
                                    }
                                ]
                            },
                        }
                    ]
                },
            )
        if request.url.path.endswith("/comments"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "reply-conflict",
                            "snippet": {"textOriginal": "changed snapshot"},
                        },
                        {
                            "id": "reply-2",
                            "snippet": {"textOriginal": "second reply"},
                        },
                    ]
                },
            )
        raise AssertionError("unexpected YouTube path")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = YouTubeHistoricalCommentClient(
                http=http,
                permit=_permit(),
                api_key="test-api-key",
            )
            await client.collect_channel("channel-conflict")

    with pytest.raises(
        AcquisitionProtocolError,
        match="same comment id is bound to different acquisition semantics",
    ):
        asyncio.run(run())


def test_youtube_reader_requires_explicit_permit_before_network() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"items": []})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = YouTubeHistoricalCommentClient(
                http=http,
                permit=None,
                api_key="test-api-key",
            )
            await client.collect_channel("channel-1")

    with pytest.raises(ExternalIntegrationDisabled):
        asyncio.run(run())
    assert calls == 0


@pytest.mark.parametrize(
    ("platform", "text_field", "reply_edge"),
    [
        ("facebook", "message", "comments"),
        ("instagram", "text", "replies"),
    ],
)
def test_meta_readers_use_get_only_and_collect_replies(
    platform: str,
    text_field: str,
    reply_edge: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "graph.facebook.com"
        if request.url.path.endswith("/source-1/comments"):
            return httpx.Response(
                200,
                json={"data": [{"id": "comment-1", text_field: "Top"}]},
            )
        if request.url.path.endswith(f"/comment-1/{reply_edge}"):
            return httpx.Response(
                200,
                json={"data": [{"id": "reply-1", text_field: "Reply"}]},
            )
        raise AssertionError(f"unexpected Meta path: {request.url.path}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MetaHistoricalCommentClient(
                http=http,
                permit=_permit(),
                access_token="test-access-token",
                api_version="v99.0",
            )
            if platform == "facebook":
                return await client.collect_facebook_posts(["source-1"])
            return await client.collect_instagram_media(["source-1"])

    batch = asyncio.run(run())
    assert batch.platform.value == platform
    assert batch.record_count == 2
    assert {comment.comment_id for comment in batch.comments} == {
        "comment-1",
        "reply-1",
    }
    assert len(requests) == 2



@pytest.mark.parametrize(
    ("platform", "text_field", "reply_edge"),
    [
        ("facebook", "message", "comments"),
        ("instagram", "text", "replies"),
    ],
)
def test_meta_collects_text_replies_under_non_text_parent(
    platform: str,
    text_field: str,
    reply_edge: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        if request.url.path.endswith("/source-empty/comments"):
            return httpx.Response(
                200,
                json={"data": [{"id": "parent-empty", text_field: ""}]},
            )
        if request.url.path.endswith(f"/parent-empty/{reply_edge}"):
            return httpx.Response(
                200,
                json={"data": [{"id": "reply-text", text_field: "Retained reply"}]},
            )
        raise AssertionError(f"unexpected Meta path: {request.url.path}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MetaHistoricalCommentClient(
                http=http,
                permit=_permit(),
                access_token="test-access-token",
                api_version="v99.0",
            )
            if platform == "facebook":
                return await client.collect_facebook_posts(["source-empty"])
            return await client.collect_instagram_media(["source-empty"])

    batch = asyncio.run(run())
    assert batch.platform.value == platform
    assert batch.record_count == 1
    assert {comment.comment_id for comment in batch.comments} == {"reply-text"}
    assert batch.comments[0].thread_id == "parent-empty"
    assert len(requests) == 2


def test_written_replay_does_not_include_author_identity(tmp_path: Path) -> None:
    export = tmp_path / "one.zip"
    html = (
        '<div class="message default clearfix" id="message1">'
        '<div class="from_name">Sensitive Name</div>'
        '<div class="text">Visible content</div></div>'
    )
    with zipfile.ZipFile(export, "w") as archive:
        archive.writestr("messages.html", html)
    batch = load_telegram_desktop_export(export)
    output = tmp_path / "out.replay.jsonl"
    write_replay_jsonl(output, batch.comments)
    payload = json.loads(output.read_text(encoding="utf-8").strip())
    assert "author_id" not in payload
    assert "Sensitive Name" not in output.read_text(encoding="utf-8")



def test_telegram_zip_caps_total_uncompressed_html_before_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.acquisition.telegram_export as telegram_export

    monkeypatch.setattr(telegram_export, "_MAX_EXPORT_BYTES", 1_000)
    export = tmp_path / "oversized.zip"
    with zipfile.ZipFile(export, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("messages.html", "a" * 600)
        archive.writestr("messages2.html", "b" * 600)

    with pytest.raises(AcquisitionLimitExceeded, match="uncompressed HTML"):
        load_telegram_desktop_export(export)


def test_telegram_duplicate_message_id_conflict_fails_closed(tmp_path: Path) -> None:
    export = tmp_path / "duplicate-id.zip"
    first = (
        '<div class="message default clearfix" id="message7">'
        '<div class="text">first</div></div>'
    )
    second = (
        '<div class="message default clearfix" id="message7">'
        '<div class="text">different</div></div>'
    )
    with zipfile.ZipFile(export, "w") as archive:
        archive.writestr("messages.html", first)
        archive.writestr("messages2.html", second)

    with pytest.raises(AcquisitionProtocolError, match="conflicting text"):
        load_telegram_desktop_export(export)


def test_merge_preserves_phase20_event_identity_and_scrubs_author(
    tmp_path: Path,
) -> None:
    source = tmp_path / "phase20.replay.jsonl"
    source.write_text(
        json.dumps(
            {
                "platform": "telegram",
                "external_event_key": "opaque-phase20-event-key",
                "external_event_id": "thread-77",
                "author_id": "sensitive-author",
                "text": "Representative text",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "merged.replay.jsonl"

    manifest = merge_replay_corpora([source], output)
    corpus = load_replay_corpus(output)

    assert manifest["record_count"] == 1
    assert corpus.records[0].external_event_key == "opaque-phase20-event-key"
    assert corpus.records[0].external_event_id == "thread-77"
    assert corpus.records[0].external_comment_id is None
    assert corpus.records[0].external_post_id is None
    assert corpus.records[0].author_id is None
    assert "sensitive-author" not in output.read_text(encoding="utf-8")


def test_merge_rejects_semantic_conflict_before_author_scrubbing(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.replay.jsonl"
    second = tmp_path / "second.replay.jsonl"
    common = {
        "platform": "telegram",
        "external_event_key": "same-event",
        "text": "same text",
    }
    first.write_text(
        json.dumps({**common, "author_id": "author-a"}) + "\n",
        encoding="utf-8",
    )
    second.write_text(
        json.dumps({**common, "author_id": "author-b"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(AcquisitionProtocolError, match="different replay semantics"):
        merge_replay_corpora([first, second], tmp_path / "merged.replay.jsonl")
