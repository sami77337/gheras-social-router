"""Async moderation orchestration over durable events and normalized adapter evidence."""

from __future__ import annotations

from app.adapters.contracts import ModerationAdapter
from app.domain.moderation import (
    ModerationAssessment,
    ModerationCategory,
    ModerationRequest,
    ModerationResult,
)
from app.persistence.moderation_repository import ModerationRepository
from app.persistence.repositories import DurableRepository
from app.services.moderation_policy import ModerationPolicy

_UNKNOWN_ADAPTER = "unknown-adapter"
_UNKNOWN_VERSION = "unknown-version"


def _safe_adapter_identity(adapter: ModerationAdapter) -> tuple[str, str]:
    try:
        name = adapter.name
        version = adapter.version
    except Exception:
        return _UNKNOWN_ADAPTER, _UNKNOWN_VERSION
    if not isinstance(name, str) or not isinstance(version, str):
        return _UNKNOWN_ADAPTER, _UNKNOWN_VERSION
    if not name.strip() or not version.strip():
        return _UNKNOWN_ADAPTER, _UNKNOWN_VERSION
    return name, version


class ModerationService:
    """Moderate one durable event exactly once at the persistence boundary."""

    def __init__(
        self,
        *,
        events: DurableRepository,
        results: ModerationRepository,
        adapter: ModerationAdapter,
        policy: ModerationPolicy,
    ) -> None:
        self.events = events
        self.results = results
        self.adapter = adapter
        self.policy = policy

    async def moderate(self, event_id: str) -> ModerationResult:
        """Return a durable routing-only moderation result for one inbound event."""

        existing = self.results.get_for_event(event_id)
        if existing is not None:
            return existing

        event = self.events.get_event(event_id)
        request = ModerationRequest(
            event_id=event.id,
            platform=event.platform,
            text=event.text,
            media=event.media,
        )
        adapter_name, adapter_version = _safe_adapter_identity(self.adapter)

        assessment: ModerationAssessment | None = None
        categories: tuple[ModerationCategory, ...] = ()
        confidence: float | None = None

        try:
            candidate = await self.adapter.assess(request)
        except Exception:
            decision = self.policy.adapter_failure()
        else:
            if not isinstance(candidate, ModerationAssessment):
                decision = self.policy.invalid_assessment()
            else:
                assessment = candidate
                categories = assessment.categories
                confidence = assessment.confidence
                decision = self.policy.decide(request, assessment)

        return self.results.create_for_event(
            event_id=event.id,
            decision=decision,
            categories=categories,
            adapter_name=adapter_name,
            adapter_version=adapter_version,
            confidence=confidence,
        )
