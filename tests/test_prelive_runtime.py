from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.contracts import ReplyPublisher
from app.adapters.models.contracts import StructuredDecisionRequest
from app.domain.classification import ClassificationRoute
from app.domain.events import NormalizedInboundEvent, Platform
from app.domain.moderation import ModerationDisposition
from app.domain.shadow import ShadowOutcome
from app.integrations.live.activation import (
    ExternalIntegrationDisabled,
    issue_sandbox_execution_permit,
)
from app.main import create_app
from app.runtime.prelive import create_prelive_sandbox_runtime

META_SECRET = "sandbox-meta-secret"
META_VERIFY_TOKEN = "sandbox-meta-verify-token"
TELEGRAM_SECRET = "Sandbox_Telegram-Webhook-Secret"


class StaticDecisionClient:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls: list[StructuredDecisionRequest] = []

    async def request(self, request: StructuredDecisionRequest) -> object:
        self.calls.append(request)
        return self.output


class RecordingPublisher(ReplyPublisher):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def publish_reply(self, *, external_comment_id: str, text: str) -> str:
        self.calls.append((external_comment_id, text))
        return f"fake-{external_comment_id}"


def _moderation_output(*, confidence: float = 0.99) -> dict[str, object]:
    return {
        "verdict": "safe",
        "severity": "none",
        "confidence": confidence,
        "categories": [],
        "text_assessed": True,
        "media_assessed": False,
    }


def _classification_output(
    *,
    route: str = "FAQ",
    confidence: float = 0.99,
    religious_possible: bool = False,
    faq_key: str | None = "registration.status",
) -> dict[str, object]:
    return {
        "proposed_route": route,
        "confidence": confidence,
        "religious_possible": religious_possible,
        "faq_key": faq_key,
    }


def _permit():
    return issue_sandbox_execution_permit(purpose="sandbox_validation")


def _runtime(
    tmp_path: Path,
    *,
    moderation_output: object | None = None,
    classification_output: object | None = None,
    publisher: RecordingPublisher | None = None,
):
    moderation_client = StaticDecisionClient(
        _moderation_output() if moderation_output is None else moderation_output
    )
    classification_client = StaticDecisionClient(
        _classification_output() if classification_output is None else classification_output
    )
    runtime = create_prelive_sandbox_runtime(
        tmp_path / "router.db",
        permit=_permit(),
        moderation_client=moderation_client,
        classification_client=classification_client,
        meta_app_secret=META_SECRET,
        meta_verify_token=META_VERIFY_TOKEN,
        telegram_webhook_secret=TELEGRAM_SECRET,
        publishers={Platform.TELEGRAM: publisher} if publisher is not None else None,
    )
    return runtime, moderation_client, classification_client


def _telegram_body(text: str = "متى يبدأ التسجيل؟") -> bytes:
    payload = {
        "update_id": 100,
        "message": {
            "message_id": 55,
            "from": {"id": 42, "is_bot": False},
            "chat": {"id": -777, "type": "private"},
            "date": 1770000000,
            "text": text,
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def test_factory_requires_explicit_sandbox_permit(tmp_path: Path) -> None:
    moderation_client = StaticDecisionClient(_moderation_output())
    classification_client = StaticDecisionClient(_classification_output())

    with pytest.raises(ExternalIntegrationDisabled):
        create_prelive_sandbox_runtime(
            tmp_path / "router.db",
            permit=None,
            moderation_client=moderation_client,
            classification_client=classification_client,
            meta_app_secret=META_SECRET,
            meta_verify_token=META_VERIFY_TOKEN,
            telegram_webhook_secret=TELEGRAM_SECRET,
        )

    assert not (tmp_path / "router.db").exists()


def test_default_fastapi_app_does_not_mount_provider_ingress() -> None:
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/integrations/meta/webhook").status_code == 404
        assert client.post("/integrations/meta/webhook", json={}).status_code == 404
        assert client.post("/integrations/telegram/webhook", json={}).status_code == 404


def test_runtime_repr_redacts_ingress_secrets(tmp_path: Path) -> None:
    runtime, _, _ = _runtime(tmp_path)

    rendered = repr(runtime)
    assert META_SECRET not in rendered
    assert META_VERIFY_TOKEN not in rendered
    assert TELEGRAM_SECRET not in rendered
    assert rendered == "PreLiveSandboxRuntime(mode='sandbox', configured=True)"


def test_telegram_ingress_to_faq_shadow_is_end_to_end_without_auto_publish(
    tmp_path: Path,
) -> None:
    publisher = RecordingPublisher()
    runtime, moderation_client, classification_client = _runtime(
        tmp_path,
        publisher=publisher,
    )
    runtime.faqs.create_version(
        faq_key="registration.status",
        answer_text="الإجابة المعتمدة حرفيًا.",
        source_ref="sandbox://faq/registration.status/v1",
        approved_by="sandbox-reviewer",
        approved_at=datetime(2026, 9, 11, 0, 0, tzinfo=UTC),
    )

    batch = runtime.ingress.telegram.ingest(
        raw_body=_telegram_body(),
        secret_header=TELEGRAM_SECRET,
    )
    assert batch.created_count == 1
    event_id = batch.results[0].event.id

    result = asyncio.run(runtime.process_event(event_id))

    assert result.moderation_disposition is ModerationDisposition.ALLOW_ROUTING
    assert result.route is ClassificationRoute.FAQ
    assert result.shadow_outcome is ShadowOutcome.WOULD_PUBLISH
    assert len(moderation_client.calls) == 1
    assert len(classification_client.calls) == 1
    assert publisher.calls == []
    assert runtime.publications.count_actions() == 0


def test_publication_remains_an_explicit_separate_operation(tmp_path: Path) -> None:
    publisher = RecordingPublisher()
    runtime, _, _ = _runtime(tmp_path, publisher=publisher)
    answer = "إجابة FAQ المعتمدة دون تعديل."
    runtime.faqs.create_version(
        faq_key="registration.status",
        answer_text=answer,
        source_ref="sandbox://faq/registration.status/v1",
        approved_by="sandbox-reviewer",
        approved_at=datetime(2026, 9, 11, 0, 0, tzinfo=UTC),
    )
    batch = runtime.ingress.telegram.ingest(
        raw_body=_telegram_body(),
        secret_header=TELEGRAM_SECRET,
    )
    event_id = batch.results[0].event.id
    asyncio.run(runtime.process_event(event_id))

    assert publisher.calls == []
    publication = asyncio.run(runtime.publishing.dispatch_origin(event_id))

    assert publication.provider_called is True
    assert publisher.calls == [("-777:55", answer)]


def test_malformed_moderation_stops_before_classification_and_publication(
    tmp_path: Path,
) -> None:
    publisher = RecordingPublisher()
    malformed = {"verdict": "safe", "answer": "not allowed"}
    runtime, moderation_client, classification_client = _runtime(
        tmp_path,
        moderation_output=malformed,
        publisher=publisher,
    )
    event_id = runtime.ingestion.ingest_event(
        NormalizedInboundEvent(
            platform=Platform.TELEGRAM,
            external_event_key="-777:56",
            external_comment_id="-777:56",
            text="مرحبا",
        )
    ).event.id

    result = asyncio.run(runtime.process_event(event_id))

    assert result.moderation_disposition is ModerationDisposition.HUMAN_REVIEW
    assert result.route is None
    assert result.shadow_outcome is ShadowOutcome.WOULD_WAIT_HUMAN
    assert len(moderation_client.calls) == 1
    assert classification_client.calls == []
    assert publisher.calls == []
    assert runtime.publications.count_actions() == 0


def test_religious_possible_creates_fatwa_request_without_generating_or_publishing(
    tmp_path: Path,
) -> None:
    publisher = RecordingPublisher()
    classification = _classification_output(
        route="FAQ",
        religious_possible=True,
        faq_key="registration.status",
    )
    runtime, _, classification_client = _runtime(
        tmp_path,
        classification_output=classification,
        publisher=publisher,
    )
    event_id = runtime.ingestion.ingest_event(
        NormalizedInboundEvent(
            platform=Platform.TELEGRAM,
            external_event_key="-777:57",
            external_comment_id="-777:57",
            text="ما حكم هذا الأمر؟",
        )
    ).event.id

    result = asyncio.run(runtime.process_event(event_id))

    assert result.route is ClassificationRoute.FATWA
    assert result.shadow_outcome is ShadowOutcome.WOULD_ROUTE_FATWA
    request = runtime.fatwas.get_for_event(event_id)
    assert request is not None
    assert len(classification_client.calls) == 1
    assert publisher.calls == []
    assert runtime.publications.count_actions() == 0
