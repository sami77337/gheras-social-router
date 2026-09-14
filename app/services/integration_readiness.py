"""Redaction-safe external-integration configuration readiness checks."""

from __future__ import annotations

from collections.abc import Iterable

from app.adapters.platforms.live_security import (
    WebhookVerificationError,
    validate_meta_graph_api_version,
    validate_telegram_webhook_secret,
)
from app.config import Settings
from app.domain.integrations import (
    IntegrationReadiness,
    IntegrationReadinessState,
    IntegrationTarget,
)


def _missing(pairs: Iterable[tuple[str, str | None]]) -> tuple[str, ...]:
    return tuple(sorted(name for name, value in pairs if value is None or not value.strip()))


class IntegrationReadinessService:
    """Report sandbox-preparation readiness without exposing configured values."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate_all(self) -> tuple[IntegrationReadiness, ...]:
        return tuple(self.evaluate(target) for target in IntegrationTarget)

    def evaluate(self, target: IntegrationTarget) -> IntegrationReadiness:
        required = self._required_values(target)
        missing = _missing(required)
        if missing:
            return IntegrationReadiness(
                target=target,
                state=IntegrationReadinessState.MISSING_CONFIG,
                missing_variables=missing,
            )

        invalid = self._invalid_variables(target)
        if invalid:
            return IntegrationReadiness(
                target=target,
                state=IntegrationReadinessState.INVALID_CONFIG,
                invalid_variables=invalid,
            )

        return IntegrationReadiness(
            target=target,
            state=IntegrationReadinessState.READY_FOR_SANDBOX_VALIDATION,
        )

    def _required_values(self, target: IntegrationTarget) -> tuple[tuple[str, str | None], ...]:
        values: dict[IntegrationTarget, tuple[tuple[str, str | None], ...]] = {
            IntegrationTarget.FACEBOOK: (
                ("META_GRAPH_API_VERSION", self.settings.meta_graph_api_version),
                ("META_PAGE_ID", self.settings.meta_page_id),
                ("META_ACCESS_TOKEN", self.settings.meta_access_token),
                ("META_APP_SECRET", self.settings.meta_app_secret),
                ("META_VERIFY_TOKEN", self.settings.meta_verify_token),
            ),
            IntegrationTarget.INSTAGRAM: (
                ("META_GRAPH_API_VERSION", self.settings.meta_graph_api_version),
                ("INSTAGRAM_BUSINESS_ACCOUNT_ID", self.settings.instagram_business_account_id),
                ("META_ACCESS_TOKEN", self.settings.meta_access_token),
                ("META_APP_SECRET", self.settings.meta_app_secret),
                ("META_VERIFY_TOKEN", self.settings.meta_verify_token),
            ),
            IntegrationTarget.TELEGRAM: (
                ("TELEGRAM_SUPERVISOR_CHAT_ID", self.settings.telegram_supervisor_chat_id),
                ("TELEGRAM_BOT_TOKEN", self.settings.telegram_bot_token),
                ("TELEGRAM_WEBHOOK_SECRET", self.settings.telegram_webhook_secret),
            ),
            IntegrationTarget.YOUTUBE: (
                ("YOUTUBE_CLIENT_ID", self.settings.youtube_client_id),
                ("YOUTUBE_CHANNEL_ID", self.settings.youtube_channel_id),
                ("YOUTUBE_CLIENT_SECRET", self.settings.youtube_client_secret),
                ("YOUTUBE_REFRESH_TOKEN", self.settings.youtube_refresh_token),
            ),
            IntegrationTarget.AI_PROVIDER: (
                ("OPENAI_API_KEY", self.settings.openai_api_key),
            ),
            IntegrationTarget.FATWA_BRIDGE: (
                ("FATWA_BRIDGE_SECRET", self.settings.fatwa_bridge_secret),
            ),
        }
        return values[target]

    def _invalid_variables(self, target: IntegrationTarget) -> tuple[str, ...]:
        invalid: list[str] = []
        if target in {IntegrationTarget.FACEBOOK, IntegrationTarget.INSTAGRAM}:
            version = self.settings.meta_graph_api_version
            if version is not None and version.strip():
                try:
                    validate_meta_graph_api_version(version)
                except WebhookVerificationError:
                    invalid.append("META_GRAPH_API_VERSION")
        if target is IntegrationTarget.TELEGRAM:
            secret = self.settings.telegram_webhook_secret
            if secret is not None and secret.strip():
                try:
                    validate_telegram_webhook_secret(secret)
                except WebhookVerificationError:
                    invalid.append("TELEGRAM_WEBHOOK_SECRET")
        return tuple(sorted(invalid))
