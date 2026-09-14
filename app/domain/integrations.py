"""Fail-closed domain model for external integration readiness."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IntegrationTarget(StrEnum):
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    TELEGRAM = "telegram"
    YOUTUBE = "youtube"
    AI_PROVIDER = "ai_provider"
    FATWA_BRIDGE = "fatwa_bridge"


class IntegrationReadinessState(StrEnum):
    MISSING_CONFIG = "missing_config"
    INVALID_CONFIG = "invalid_config"
    READY_FOR_SANDBOX_VALIDATION = "ready_for_sandbox_validation"


@dataclass(frozen=True, slots=True)
class IntegrationReadiness:
    """Redaction-safe readiness result; never contains credential values."""

    target: IntegrationTarget
    state: IntegrationReadinessState
    missing_variables: tuple[str, ...] = ()
    invalid_variables: tuple[str, ...] = ()
    live_activation_allowed: bool = False

    def __post_init__(self) -> None:
        if self.live_activation_allowed:
            raise ValueError("Phase 11 cannot authorize live activation")
        if self.state is IntegrationReadinessState.MISSING_CONFIG and not self.missing_variables:
            raise ValueError("missing_config requires missing variable names")
        if self.state is IntegrationReadinessState.INVALID_CONFIG and not self.invalid_variables:
            raise ValueError("invalid_config requires invalid variable names")
        if (
            self.state is IntegrationReadinessState.READY_FOR_SANDBOX_VALIDATION
            and (self.missing_variables or self.invalid_variables)
        ):
            raise ValueError("ready readiness cannot contain configuration findings")
