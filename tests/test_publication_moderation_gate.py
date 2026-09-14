from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.adapters.models.contracts import StructuredDecisionRequest
from app.domain.classification import (
    ClassificationDecision,
    ClassificationReason,
    ClassificationRoute,
)
from app.domain.events import NormalizedInboundEvent, Platform
from app.integrations.live.activation import issue_sandbox_execution_permit
from app.runtime.prelive import create_prelive_sandbox_runtime
from app.services.publishing import PublishingNotEligible


class StaticDecisionClient:
    def __init__(self, output: object) -> None:
        self.output = output

    async def request(self, request: StructuredDecisionRequest) -> object:
        return self.output


def test_publication_rechecks_effective_moderation_before_route_evidence(
    tmp_path: Path,
) -> None:
    runtime = create_prelive_sandbox_runtime(
        tmp_path / "router.db",
        permit=issue_sandbox_execution_permit(purpose="sandbox_validation"),
        moderation_client=StaticDecisionClient(
            {"verdict": "safe", "answer": "forbidden-output-surface"}
        ),
        classification_client=StaticDecisionClient(
            {
                "proposed_route": "FAQ",
                "confidence": 0.99,
                "religious_possible": False,
                "faq_key": "registration.status",
            }
        ),
        meta_app_secret="meta-secret",
        meta_verify_token="meta-verify",
        telegram_webhook_secret="Telegram_Publish-Gate",
    )
    event_id = runtime.ingestion.ingest_event(
        NormalizedInboundEvent(
            platform=Platform.TELEGRAM,
            external_event_key="publication:moderation-gate",
            external_comment_id="publication:moderation-gate",
            text="محتوى قيد المراجعة",
        )
    ).event.id

    waiting = asyncio.run(runtime.process_event(event_id))
    assert waiting.route is None
    assert runtime.moderation_review_results.get_for_event(event_id) is not None

    runtime.classification_results.create_for_event(
        event_id=event_id,
        decision=ClassificationDecision(
            route=ClassificationRoute.FAQ,
            reasons=(ClassificationReason.CONFIDENT_FAQ,),
            faq_key="registration.status",
        ),
        religious_possible=False,
        confidence=0.99,
        adapter_name="adversarial-insert",
        adapter_version="v1",
    )

    with pytest.raises(PublishingNotEligible, match="moderation allow_routing"):
        runtime.publishing.resolve_content(event_id)

    assert runtime.publications.count_actions() == 0
