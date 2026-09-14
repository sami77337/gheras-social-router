"""Application configuration loaded exclusively from process environment variables."""

from __future__ import annotations

from dataclasses import dataclass, field
from os import getenv
from typing import Literal

EnvironmentName = Literal["development", "test", "production"]


def _environment_name(value: str | None) -> EnvironmentName:
    normalized = (value or "development").strip().lower()
    if normalized not in {"development", "test", "production"}:
        raise ValueError("APP_ENV must be one of: development, test, production")
    return normalized  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings loaded from the process environment only.

    Secret-bearing fields are intentionally excluded from repr output. Merely
    providing configuration does not authorize live network calls or publishing.
    """

    app_name: str = "Gheras Social Router"
    service_name: str = "gheras-social-router"
    environment: EnvironmentName = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./data/gheras_router.db"

    meta_graph_api_version: str | None = None
    meta_page_id: str | None = None
    instagram_business_account_id: str | None = None
    telegram_supervisor_chat_id: str | None = None
    youtube_client_id: str | None = None
    youtube_channel_id: str | None = None

    openai_api_key: str | None = field(default=None, repr=False)
    meta_access_token: str | None = field(default=None, repr=False)
    meta_app_secret: str | None = field(default=None, repr=False)
    meta_verify_token: str | None = field(default=None, repr=False)
    telegram_bot_token: str | None = field(default=None, repr=False)
    telegram_webhook_secret: str | None = field(default=None, repr=False)
    youtube_client_secret: str | None = field(default=None, repr=False)
    youtube_refresh_token: str | None = field(default=None, repr=False)
    fatwa_bridge_secret: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from process environment variables only."""

        return cls(
            app_name=getenv("APP_NAME", "Gheras Social Router"),
            service_name=getenv("SERVICE_NAME", "gheras-social-router"),
            environment=_environment_name(getenv("APP_ENV")),
            log_level=getenv("LOG_LEVEL", "INFO").upper(),
            database_url=getenv("DATABASE_URL", "sqlite:///./data/gheras_router.db"),
            meta_graph_api_version=getenv("META_GRAPH_API_VERSION"),
            meta_page_id=getenv("META_PAGE_ID"),
            instagram_business_account_id=getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID"),
            telegram_supervisor_chat_id=getenv("TELEGRAM_SUPERVISOR_CHAT_ID"),
            youtube_client_id=getenv("YOUTUBE_CLIENT_ID"),
            youtube_channel_id=getenv("YOUTUBE_CHANNEL_ID"),
            openai_api_key=getenv("OPENAI_API_KEY"),
            meta_access_token=getenv("META_ACCESS_TOKEN"),
            meta_app_secret=getenv("META_APP_SECRET"),
            meta_verify_token=getenv("META_VERIFY_TOKEN"),
            telegram_bot_token=getenv("TELEGRAM_BOT_TOKEN"),
            telegram_webhook_secret=getenv("TELEGRAM_WEBHOOK_SECRET"),
            youtube_client_secret=getenv("YOUTUBE_CLIENT_SECRET"),
            youtube_refresh_token=getenv("YOUTUBE_REFRESH_TOKEN"),
            fatwa_bridge_secret=getenv("FATWA_BRIDGE_SECRET"),
        )
