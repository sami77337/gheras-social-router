from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.adapters.models.contracts import StructuredDecisionRequest
from app.domain.classification import ClassificationRoute
from app.domain.events import NormalizedInboundEvent, Platform
from app.domain.moderation import ModerationDisposition
from app.domain.moderation_review import (
    ModerationHumanDecision,
    ModerationHumanReviewStatus,
)
from app.domain.shadow import ShadowOutcome
from app.integrations.live.activation import issue_sandbox_execution_permit
from app.persistence.moderation_review_repository import ModerationReviewConflict
from app.runtime.prelive import create_prelive_sandbox_runtime
from app.services.moderation_review import ModerationReviewNotEligible


class StaticDecisionClient:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls: list[StructuredDecisionRequest] = []

    async def request(self, request: StructuredDecisionRequest) -> object:
        self.calls.append(request)
        return self.output


def _safe_moderation() -> dict[str, object]:
    return {
        "verdict": "safe",
        "severity": "none",
        "confidence": 0.99,
        "categories": [],
        "text_assessed": True,
        "media_assessed": False,
    }


def _malformed_moderation() -> dict[str, object]:
    return {"verdict": "safe", "answer": "forbidden-output-surface"}


def _faq_classification() -> dict[str, object]:
    return {
        "proposed_route": "FAQ",
        "confidence": 0.99,
        "religious_possible": False,
        "faq_key": "registration.status",
    }


def _runtime(
    database_path: Path,
    *,
    moderation_output: object,
) -> tuple[object, StaticDecisionClient, StaticDecisionClient]:
    moderation_client = StaticDecisionClient(moderation_output)
    classification_client = StaticDecisionClient(_faq_classification())
    runtime = create_prelive_sandbox_runtime(
        database_path,
        permit=issue_sandbox_execution_permit(purpose="sandbox_validation"),
        moderation_client=moderation_client,
        classification_client=classification_client,
        meta_app_secret="meta-secret",
        meta_verify_token="meta-verify",
        telegram_webhook_secret="Telegram_Review-Secret",
    )
    return runtime, moderation_client, classification_client


def _ingest(runtime: object, *, key: str) -> str:
    return runtime.ingestion.ingest_event(  # type: ignore[attr-defined]
        NormalizedInboundEvent(
            platform=Platform.TELEGRAM,
            external_event_key=key,
            external_comment_id=key,
            text="محتوى يحتاج مراجعة بشرية",
        )
    ).event.id


def _seed_faq(runtime: object) -> None:
    runtime.faqs.create_version(  # type: ignore[attr-defined]
        faq_key="registration.status",
        answer_text="الإجابة المعتمدة حرفيًا.",
        source_ref="sandbox://faq/registration.status/v1",
        approved_by="faq-reviewer",
        approved_at=datetime(2026, 9, 11, 0, 0, tzinfo=UTC),
    )


def test_human_review_is_durable_and_stops_before_classification(tmp_path: Path) -> None:
    runtime, moderation_client, classification_client = _runtime(
        tmp_path / "router.db",
        moderation_output=_malformed_moderation(),
    )
    event_id = _ingest(runtime, key="review:pending")

    result = asyncio.run(runtime.process_event(event_id))  # type: ignore[attr-defined]

    assert result.moderation_disposition is ModerationDisposition.HUMAN_REVIEW
    assert result.route is None
    assert result.shadow_outcome is ShadowOutcome.WOULD_WAIT_HUMAN
    review = runtime.moderation_review_results.get_for_event(event_id)  # type: ignore[attr-defined]
    assert review is not None
    assert review.status is ModerationHumanReviewStatus.PENDING
    assert review.decision is None
    assert runtime.moderation_review_results.count_reviews() == 1  # type: ignore[attr-defined]
    assert runtime.shadows.count() == 0  # type: ignore[attr-defined]
    assert len(moderation_client.calls) == 1
    assert classification_client.calls == []


def test_allow_review_resumes_after_restart_and_preserves_machine_result(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "router.db"
    runtime, _, first_classifier = _runtime(
        database_path,
        moderation_output=_malformed_moderation(),
    )
    _seed_faq(runtime)
    event_id = _ingest(runtime, key="review:allow")
    first = asyncio.run(runtime.process_event(event_id))  # type: ignore[attr-defined]
    assert first.shadow_outcome is ShadowOutcome.WOULD_WAIT_HUMAN
    assert first_classifier.calls == []

    review = runtime.moderation_review.resolve(  # type: ignore[attr-defined]
        event_id,
        decision=ModerationHumanDecision.ALLOW_ROUTING,
        reviewer_ref="moderator-1",
        external_review_key="review-allow-1",
    )
    assert review.status is ModerationHumanReviewStatus.RESOLVED
    assert review.decision is ModerationHumanDecision.ALLOW_ROUTING

    restarted, moderation_client, classification_client = _runtime(
        database_path,
        moderation_output=_malformed_moderation(),
    )
    resumed = asyncio.run(restarted.process_event(event_id))  # type: ignore[attr-defined]

    assert resumed.moderation_disposition is ModerationDisposition.HUMAN_REVIEW
    assert resumed.route is ClassificationRoute.FAQ
    assert resumed.shadow_outcome is ShadowOutcome.WOULD_PUBLISH
    assert moderation_client.calls == []
    assert len(classification_client.calls) == 1
    durable_machine = restarted.moderation_results.get_for_event(event_id)  # type: ignore[attr-defined]
    assert durable_machine is not None
    assert durable_machine.disposition is ModerationDisposition.HUMAN_REVIEW
    assert restarted.shadows.count() == 1  # type: ignore[attr-defined]


def test_block_review_never_calls_classifier_and_records_blocked_shadow(
    tmp_path: Path,
) -> None:
    runtime, _, classification_client = _runtime(
        tmp_path / "router.db",
        moderation_output=_malformed_moderation(),
    )
    event_id = _ingest(runtime, key="review:block")
    asyncio.run(runtime.process_event(event_id))  # type: ignore[attr-defined]

    runtime.moderation_review.resolve(  # type: ignore[attr-defined]
        event_id,
        decision=ModerationHumanDecision.BLOCK_ROUTING,
        reviewer_ref="moderator-2",
        external_review_key="review-block-1",
    )
    result = asyncio.run(runtime.process_event(event_id))  # type: ignore[attr-defined]

    assert result.moderation_disposition is ModerationDisposition.HUMAN_REVIEW
    assert result.route is None
    assert result.shadow_outcome is ShadowOutcome.BLOCKED
    assert classification_client.calls == []
    assert runtime.classification_results.get_for_event(event_id) is None  # type: ignore[attr-defined]
    assert runtime.publications.count_actions() == 0  # type: ignore[attr-defined]


def test_review_resolution_is_idempotent_and_conflicting_reuse_fails_closed(
    tmp_path: Path,
) -> None:
    runtime, _, _ = _runtime(
        tmp_path / "router.db",
        moderation_output=_malformed_moderation(),
    )
    event_id = _ingest(runtime, key="review:idempotent")
    asyncio.run(runtime.process_event(event_id))  # type: ignore[attr-defined]

    first = runtime.moderation_review.resolve(  # type: ignore[attr-defined]
        event_id,
        decision=ModerationHumanDecision.ALLOW_ROUTING,
        reviewer_ref="moderator-3",
        external_review_key="review-idempotent-1",
    )
    duplicate = runtime.moderation_review.resolve(  # type: ignore[attr-defined]
        event_id,
        decision=ModerationHumanDecision.ALLOW_ROUTING,
        reviewer_ref="moderator-3",
        external_review_key="review-idempotent-1",
    )
    assert duplicate == first

    with pytest.raises(ModerationReviewConflict):
        runtime.moderation_review.resolve(  # type: ignore[attr-defined]
            event_id,
            decision=ModerationHumanDecision.BLOCK_ROUTING,
            reviewer_ref="moderator-3",
            external_review_key="review-idempotent-1",
        )


def test_allow_routing_machine_result_cannot_create_human_override(tmp_path: Path) -> None:
    runtime, _, _ = _runtime(
        tmp_path / "router.db",
        moderation_output=_safe_moderation(),
    )
    event_id = _ingest(runtime, key="review:not-eligible")
    asyncio.run(runtime.moderation.moderate(event_id))  # type: ignore[attr-defined]

    with pytest.raises(ModerationReviewNotEligible):
        runtime.moderation_review.ensure_review(event_id)  # type: ignore[attr-defined]

    assert runtime.moderation_review_results.count_reviews() == 0  # type: ignore[attr-defined]
