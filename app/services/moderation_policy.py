"""Deterministic fail-closed policy for normalized moderation evidence."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.moderation import (
    ModerationAssessment,
    ModerationDecision,
    ModerationDisposition,
    ModerationReason,
    ModerationRequest,
    ModerationSeverity,
    ModerationVerdict,
)


@dataclass(frozen=True, slots=True)
class ModerationPolicy:
    """Map normalized moderation evidence to a routing-only disposition."""

    minimum_confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between 0 and 1")

    def decide(
        self,
        request: ModerationRequest,
        assessment: ModerationAssessment,
    ) -> ModerationDecision:
        """Apply deterministic V1 moderation rules without external side effects."""

        coverage_reasons: list[ModerationReason] = []
        if request.has_text and not assessment.text_assessed:
            coverage_reasons.append(ModerationReason.TEXT_UNASSESSED)
        if request.has_media and not assessment.media_assessed:
            coverage_reasons.append(ModerationReason.MEDIA_UNASSESSED)
        if not request.has_text and not request.has_media:
            coverage_reasons.append(ModerationReason.NO_ASSESSABLE_CONTENT)
        if coverage_reasons:
            return ModerationDecision(
                disposition=ModerationDisposition.HUMAN_REVIEW,
                reasons=tuple(coverage_reasons),
            )

        if assessment.confidence < self.minimum_confidence:
            return ModerationDecision(
                disposition=ModerationDisposition.HUMAN_REVIEW,
                reasons=(ModerationReason.LOW_CONFIDENCE,),
            )

        if assessment.verdict is ModerationVerdict.UNCERTAIN:
            return ModerationDecision(
                disposition=ModerationDisposition.HUMAN_REVIEW,
                reasons=(ModerationReason.UNCERTAIN_VERDICT,),
            )

        if assessment.verdict is ModerationVerdict.SAFE:
            if (
                assessment.severity is not ModerationSeverity.NONE
                or bool(assessment.categories)
            ):
                return ModerationDecision(
                    disposition=ModerationDisposition.HUMAN_REVIEW,
                    reasons=(ModerationReason.INVALID_ASSESSMENT,),
                )
            return ModerationDecision(
                disposition=ModerationDisposition.ALLOW_ROUTING,
                reasons=(ModerationReason.EXPLICIT_SAFE,),
            )

        if assessment.verdict is ModerationVerdict.UNSAFE:
            if assessment.severity in {
                ModerationSeverity.MEDIUM,
                ModerationSeverity.HIGH,
            }:
                return ModerationDecision(
                    disposition=ModerationDisposition.BLOCK_ROUTING,
                    reasons=(ModerationReason.EXPLICIT_UNSAFE,),
                )
            return ModerationDecision(
                disposition=ModerationDisposition.HUMAN_REVIEW,
                reasons=(ModerationReason.EXPLICIT_UNSAFE,),
            )

        return ModerationDecision(
            disposition=ModerationDisposition.HUMAN_REVIEW,
            reasons=(ModerationReason.INVALID_ASSESSMENT,),
        )

    @staticmethod
    def adapter_failure() -> ModerationDecision:
        """Fail closed when the moderation adapter cannot provide evidence."""

        return ModerationDecision(
            disposition=ModerationDisposition.HUMAN_REVIEW,
            reasons=(ModerationReason.ADAPTER_FAILURE,),
        )

    @staticmethod
    def invalid_assessment() -> ModerationDecision:
        """Fail closed when an adapter violates the normalized contract."""

        return ModerationDecision(
            disposition=ModerationDisposition.HUMAN_REVIEW,
            reasons=(ModerationReason.INVALID_ASSESSMENT,),
        )
