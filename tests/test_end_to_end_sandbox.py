from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.classification import ClassificationAssessment, ClassificationRoute
from app.domain.events import NormalizedInboundEvent, Platform
from app.domain.fatwa import FatwaResultOutcome
from app.domain.moderation import (
    ModerationAssessment,
    ModerationDisposition,
    ModerationSeverity,
    ModerationVerdict,
)
from app.domain.publishing import (
    FatwaPublicationPolicy,
    PublicationSourceKind,
    PublicationStatus,
)
from app.domain.shadow import ShadowOutcome
from app.sandbox.replay import (
    ReplayEvidenceConflict,
    ReplayFAQApproval,
    ReplayFatwaEvidence,
    ReplayScenario,
    ReplaySupervisorEvidence,
    SandboxReplayRuntime,
)

NOW = datetime(2026, 9, 10, 13, 0, tzinfo=UTC)
FAQ_TEXT = "الإجابة المعتمدة حرفيًا من قاعدة الأسئلة الشائعة."
SUPERVISOR_TEXT = "الإجابة البشرية المعتمدة حرفيًا."
FATWA_TEXT = "جواب الجهة الشرعية المعتمد حرفيًا دون تعديل."


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


def _safe_moderation(*, confidence: float = 0.99) -> ModerationAssessment:
    return ModerationAssessment(
        verdict=ModerationVerdict.SAFE,
        severity=ModerationSeverity.NONE,
        confidence=confidence,
        text_assessed=True,
    )


def _faq_classification(
    *,
    confidence: float = 0.99,
    religious_possible: bool = False,
) -> ClassificationAssessment:
    return ClassificationAssessment(
        proposed_route=ClassificationRoute.FAQ,
        confidence=confidence,
        religious_possible=religious_possible,
        faq_key="registration.status",
    )


def _faq_approval(*, answer: str = FAQ_TEXT) -> ReplayFAQApproval:
    return ReplayFAQApproval(
        faq_key="registration.status",
        answer_text=answer,
        source_ref="sandbox://approved-faq/registration.status/v1",
        approved_by="sandbox-reviewer",
        approved_at=NOW,
    )


def _event(
    platform: Platform,
    *,
    suffix: str,
    text: str = "متى يبدأ التسجيل؟",
) -> NormalizedInboundEvent:
    target = {
        Platform.FACEBOOK: f"fb-comment-{suffix}",
        Platform.INSTAGRAM: f"ig-comment-{suffix}",
        Platform.TELEGRAM: f"-100777:{suffix}",
        Platform.YOUTUBE: f"yt-comment-{suffix}",
    }[platform]
    return NormalizedInboundEvent(
        platform=platform,
        external_event_key=f"{platform.value}-event-{suffix}",
        external_comment_id=target,
        external_post_id=f"{platform.value}-post-{suffix}",
        author_id=f"{platform.value}-author-{suffix}",
        text=text,
    )


def _faq_scenario(platform: Platform, *, suffix: str) -> ReplayScenario:
    return ReplayScenario(
        event=_event(platform, suffix=suffix),
        moderation=_safe_moderation(),
        classification=_faq_classification(),
        faq_approval=_faq_approval(),
    )


@pytest.mark.parametrize("platform", list(Platform))
def test_four_platform_faq_matrix_publishes_only_approved_exact_text_fingerprint(
    tmp_path: Path,
    platform: Platform,
) -> None:
    runtime = SandboxReplayRuntime(tmp_path / f"{platform.value}.db")
    result = _run(runtime.replay_one(_faq_scenario(platform, suffix="1")))

    assert result.platform is platform  # type: ignore[union-attr]
    assert result.created_event is True  # type: ignore[union-attr]
    assert result.moderation_disposition is ModerationDisposition.ALLOW_ROUTING  # type: ignore[union-attr]
    assert result.route is ClassificationRoute.FAQ  # type: ignore[union-attr]
    assert result.shadow_outcome is ShadowOutcome.WOULD_PUBLISH  # type: ignore[union-attr]
    assert result.source_kind is PublicationSourceKind.FAQ  # type: ignore[union-attr]
    assert result.publication_status is PublicationStatus.SUCCEEDED  # type: ignore[union-attr]
    assert result.provider_called is True  # type: ignore[union-attr]

    calls = runtime.recorded_calls
    assert len(calls) == 1
    assert calls[0].platform is platform
    assert calls[0].text_sha256 == hashlib.sha256(FAQ_TEXT.encode("utf-8")).hexdigest()
    assert calls[0].text_length == len(FAQ_TEXT)


def test_supervisor_route_requires_and_publishes_exact_human_response_fingerprint(
    tmp_path: Path,
) -> None:
    runtime = SandboxReplayRuntime(tmp_path / "router.db")
    scenario = ReplayScenario(
        event=_event(Platform.TELEGRAM, suffix="55", text="أحتاج مساعدة بشرية"),
        moderation=_safe_moderation(),
        classification=ClassificationAssessment(
            proposed_route=ClassificationRoute.SUPERVISOR,
            confidence=0.99,
            religious_possible=False,
        ),
        supervisor=ReplaySupervisorEvidence(
            transport_name="telegram",
            external_thread_id="sandbox-thread-55",
            external_response_key="sandbox-response-55",
            supervisor_ref="supervisor-1",
            text=SUPERVISOR_TEXT,
            received_at=NOW,
        ),
    )

    result = _run(runtime.replay_one(scenario))

    assert result.route is ClassificationRoute.SUPERVISOR  # type: ignore[union-attr]
    assert result.shadow_outcome is ShadowOutcome.WOULD_PUBLISH  # type: ignore[union-attr]
    assert result.source_kind is PublicationSourceKind.SUPERVISOR  # type: ignore[union-attr]
    assert result.provider_called is True  # type: ignore[union-attr]
    assert runtime.recorded_calls[0].text_sha256 == hashlib.sha256(
        SUPERVISOR_TEXT.encode("utf-8")
    ).hexdigest()


def test_supervisor_route_without_human_response_waits_and_creates_no_outbound_action(
    tmp_path: Path,
) -> None:
    runtime = SandboxReplayRuntime(tmp_path / "router.db")
    scenario = ReplayScenario(
        event=_event(Platform.INSTAGRAM, suffix="2"),
        moderation=_safe_moderation(),
        classification=ClassificationAssessment(
            proposed_route=ClassificationRoute.SUPERVISOR,
            confidence=0.99,
            religious_possible=False,
        ),
    )

    result = _run(runtime.replay_one(scenario))

    assert result.shadow_outcome is ShadowOutcome.WOULD_WAIT_HUMAN  # type: ignore[union-attr]
    assert result.publication_status is None  # type: ignore[union-attr]
    assert result.provider_called is False  # type: ignore[union-attr]
    assert runtime.publications.count_actions() == 0
    assert runtime.recorded_calls == ()


def test_approved_fatwa_stays_origin_blocked_under_default_policy(tmp_path: Path) -> None:
    runtime = SandboxReplayRuntime(tmp_path / "router.db")
    scenario = ReplayScenario(
        event=_event(Platform.FACEBOOK, suffix="fatwa", text="ما حكم هذه المسألة؟"),
        moderation=_safe_moderation(),
        classification=_faq_classification(religious_possible=True),
        fatwa=ReplayFatwaEvidence(
            bridge_name="sandbox-fatwa-bridge",
            external_case_id="case-fatwa-1",
            external_result_key="result-fatwa-1",
            outcome=FatwaResultOutcome.APPROVED,
            answer_text=FATWA_TEXT,
            approved_by="scholar-reviewer",
            source_ref="sandbox://fatwa/result/1",
            received_at=NOW,
        ),
    )

    result = _run(runtime.replay_one(scenario))

    assert result.route is ClassificationRoute.FATWA  # type: ignore[union-attr]
    assert result.shadow_outcome is ShadowOutcome.WOULD_ROUTE_FATWA  # type: ignore[union-attr]
    assert result.publication_status is None  # type: ignore[union-attr]
    assert result.provider_called is False  # type: ignore[union-attr]
    assert runtime.recorded_calls == ()
    assert runtime.publications.count_actions() == 0


def test_explicit_sandbox_origin_fatwa_policy_uses_only_approved_external_fingerprint(
    tmp_path: Path,
) -> None:
    runtime = SandboxReplayRuntime(
        tmp_path / "router.db",
        fatwa_policy=FatwaPublicationPolicy.ORIGIN_ONLY,
    )
    scenario = ReplayScenario(
        event=_event(Platform.YOUTUBE, suffix="fatwa", text="سؤال شرعي"),
        moderation=_safe_moderation(),
        classification=ClassificationAssessment(
            proposed_route=ClassificationRoute.FATWA,
            confidence=0.99,
            religious_possible=True,
        ),
        fatwa=ReplayFatwaEvidence(
            bridge_name="sandbox-fatwa-bridge",
            external_case_id="case-fatwa-2",
            external_result_key="result-fatwa-2",
            outcome=FatwaResultOutcome.APPROVED,
            answer_text=FATWA_TEXT,
            approved_by="scholar-reviewer",
            source_ref="sandbox://fatwa/result/2",
            received_at=NOW,
        ),
    )

    result = _run(runtime.replay_one(scenario))

    assert result.shadow_outcome is ShadowOutcome.WOULD_PUBLISH  # type: ignore[union-attr]
    assert result.source_kind is PublicationSourceKind.FATWA  # type: ignore[union-attr]
    assert runtime.recorded_calls[0].text_sha256 == hashlib.sha256(
        FATWA_TEXT.encode("utf-8")
    ).hexdigest()


def test_moderation_human_review_stops_classification_and_all_outbound_work(tmp_path: Path) -> None:
    runtime = SandboxReplayRuntime(tmp_path / "router.db")
    scenario = ReplayScenario(
        event=_event(Platform.YOUTUBE, suffix="low-mod"),
        moderation=_safe_moderation(confidence=0.20),
    )

    result = _run(runtime.replay_one(scenario))

    assert result.moderation_disposition is ModerationDisposition.HUMAN_REVIEW  # type: ignore[union-attr]
    assert result.route is None  # type: ignore[union-attr]
    assert result.shadow_outcome is ShadowOutcome.WOULD_WAIT_HUMAN  # type: ignore[union-attr]
    assert runtime.classifications.count_results() == 0
    assert runtime.publications.count_actions() == 0
    assert runtime.recorded_calls == ()


def test_low_confidence_faq_is_deterministically_routed_to_supervisor(tmp_path: Path) -> None:
    runtime = SandboxReplayRuntime(tmp_path / "router.db")
    scenario = ReplayScenario(
        event=_event(Platform.FACEBOOK, suffix="low-class"),
        moderation=_safe_moderation(),
        classification=_faq_classification(confidence=0.20),
    )

    result = _run(runtime.replay_one(scenario))

    assert result.route is ClassificationRoute.SUPERVISOR  # type: ignore[union-attr]
    assert result.shadow_outcome is ShadowOutcome.WOULD_WAIT_HUMAN  # type: ignore[union-attr]
    assert runtime.publications.count_actions() == 0


def test_duplicate_replay_converges_without_duplicate_event_action_or_provider_call(
    tmp_path: Path,
) -> None:
    runtime = SandboxReplayRuntime(tmp_path / "router.db")
    scenario = _faq_scenario(Platform.FACEBOOK, suffix="dup")

    first = _run(runtime.replay_one(scenario))
    second = _run(runtime.replay_one(scenario))

    assert first.created_event is True  # type: ignore[union-attr]
    assert first.provider_called is True  # type: ignore[union-attr]
    assert second.created_event is False  # type: ignore[union-attr]
    assert second.provider_called is False  # type: ignore[union-attr]
    assert runtime.events.count_events() == 1
    assert runtime.publications.count_actions() == 1
    assert len(runtime.recorded_calls) == 1


def test_restart_replay_preserves_event_and_publication_idempotency(tmp_path: Path) -> None:
    database_path = tmp_path / "router.db"
    scenario = _faq_scenario(Platform.TELEGRAM, suffix="restart")

    first_runtime = SandboxReplayRuntime(database_path)
    first = _run(first_runtime.replay_one(scenario))
    assert first.provider_called is True  # type: ignore[union-attr]

    restarted = SandboxReplayRuntime(database_path)
    second = _run(restarted.replay_one(scenario))

    assert second.created_event is False  # type: ignore[union-attr]
    assert second.provider_called is False  # type: ignore[union-attr]
    assert restarted.events.count_events() == 1
    assert restarted.publications.count_actions() == 1
    assert restarted.recorded_calls == ()


def test_replay_rejects_changed_moderation_or_classification_evidence(tmp_path: Path) -> None:
    runtime = SandboxReplayRuntime(tmp_path / "router.db")
    scenario = _faq_scenario(Platform.INSTAGRAM, suffix="drift")
    _run(runtime.replay_one(scenario))

    changed_moderation = replace(
        scenario,
        moderation=_safe_moderation(confidence=0.95),
    )
    with pytest.raises(ReplayEvidenceConflict, match="moderation"):
        _run(runtime.replay_one(changed_moderation))

    changed_classification = replace(
        scenario,
        classification=_faq_classification(confidence=0.95),
    )
    with pytest.raises(ReplayEvidenceConflict, match="classification"):
        _run(runtime.replay_one(changed_classification))


def test_replay_rejects_changed_active_faq_approval(tmp_path: Path) -> None:
    runtime = SandboxReplayRuntime(tmp_path / "router.db")
    scenario = _faq_scenario(Platform.FACEBOOK, suffix="faq-drift")
    _run(runtime.replay_one(scenario))

    changed = replace(
        scenario,
        faq_approval=_faq_approval(answer="نص مختلف غير معتمد في التشغيل الأول"),
    )
    with pytest.raises(ReplayEvidenceConflict, match="FAQ approval"):
        _run(runtime.replay_one(changed))


def test_wrong_route_downstream_evidence_fails_closed(tmp_path: Path) -> None:
    runtime = SandboxReplayRuntime(tmp_path / "router.db")
    scenario = ReplayScenario(
        event=_event(Platform.TELEGRAM, suffix="wrong-evidence"),
        moderation=_safe_moderation(),
        classification=ClassificationAssessment(
            proposed_route=ClassificationRoute.SUPERVISOR,
            confidence=0.99,
            religious_possible=False,
        ),
        faq_approval=_faq_approval(),
    )

    with pytest.raises(ReplayEvidenceConflict, match="SUPERVISOR route"):
        _run(runtime.replay_one(scenario))


def test_replay_report_is_content_free_and_aggregates_four_platform_matrix(
    tmp_path: Path,
) -> None:
    runtime = SandboxReplayRuntime(tmp_path / "router.db")
    scenarios = tuple(
        _faq_scenario(platform, suffix=f"report-{index}")
        for index, platform in enumerate(Platform, start=1)
    )

    report = _run(runtime.replay(scenarios))
    rendered = repr(report)

    assert report.provider_call_count == 4  # type: ignore[union-attr]
    assert report.by_platform == {  # type: ignore[union-attr]
        "facebook": 1,
        "instagram": 1,
        "telegram": 1,
        "youtube": 1,
    }
    assert report.by_route == {"FAQ": 4}  # type: ignore[union-attr]
    assert report.by_shadow_outcome == {"would_publish": 4}  # type: ignore[union-attr]
    assert FAQ_TEXT not in rendered
    assert SUPERVISOR_TEXT not in rendered
    assert FATWA_TEXT not in rendered
