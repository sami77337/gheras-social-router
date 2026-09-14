"""Deterministic fail-closed routing policy for classifier evidence."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.classification import (
    ClassificationAssessment,
    ClassificationDecision,
    ClassificationReason,
    ClassificationRequest,
    ClassificationRoute,
)

_MAX_FAQ_KEY_LENGTH = 128


def _valid_faq_key(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_FAQ_KEY_LENGTH:
        return False
    return not any(char.isspace() for char in normalized)


@dataclass(frozen=True, slots=True)
class ClassificationPolicy:
    """Apply Gheras religious-safety and low-confidence routing rules."""

    minimum_faq_confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_faq_confidence <= 1.0:
            raise ValueError("minimum_faq_confidence must be between 0 and 1")

    def decide(
        self,
        request: ClassificationRequest,
        assessment: ClassificationAssessment,
    ) -> ClassificationDecision:
        """Return the local authoritative route from normalized evidence."""

        if assessment.religious_possible:
            return ClassificationDecision(
                route=ClassificationRoute.FATWA,
                reasons=(ClassificationReason.RELIGIOUS_SAFETY_OVERRIDE,),
            )

        if not request.has_text:
            return ClassificationDecision(
                route=ClassificationRoute.SUPERVISOR,
                reasons=(ClassificationReason.NO_CLASSIFIABLE_TEXT,),
            )

        if assessment.proposed_route is ClassificationRoute.FATWA:
            return ClassificationDecision(
                route=ClassificationRoute.FATWA,
                reasons=(ClassificationReason.EXPLICIT_FATWA,),
            )

        if assessment.proposed_route is ClassificationRoute.SUPERVISOR:
            return ClassificationDecision(
                route=ClassificationRoute.SUPERVISOR,
                reasons=(ClassificationReason.EXPLICIT_SUPERVISOR,),
            )

        if assessment.proposed_route is ClassificationRoute.FAQ:
            if assessment.confidence < self.minimum_faq_confidence:
                return ClassificationDecision(
                    route=ClassificationRoute.SUPERVISOR,
                    reasons=(ClassificationReason.LOW_CONFIDENCE,),
                )
            if not _valid_faq_key(assessment.faq_key):
                return ClassificationDecision(
                    route=ClassificationRoute.SUPERVISOR,
                    reasons=(ClassificationReason.FAQ_KEY_MISSING,),
                )
            assert assessment.faq_key is not None
            return ClassificationDecision(
                route=ClassificationRoute.FAQ,
                reasons=(ClassificationReason.CONFIDENT_FAQ,),
                faq_key=assessment.faq_key.strip(),
            )

        return self.invalid_assessment()

    @staticmethod
    def adapter_failure() -> ClassificationDecision:
        """Fail closed to human supervision when the classifier is unavailable."""

        return ClassificationDecision(
            route=ClassificationRoute.SUPERVISOR,
            reasons=(ClassificationReason.ADAPTER_FAILURE,),
        )

    @staticmethod
    def invalid_assessment() -> ClassificationDecision:
        """Fail closed when structured classifier evidence violates the contract."""

        return ClassificationDecision(
            route=ClassificationRoute.SUPERVISOR,
            reasons=(ClassificationReason.INVALID_ASSESSMENT,),
        )
