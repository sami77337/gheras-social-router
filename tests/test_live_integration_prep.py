from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import pytest

from app.adapters.platforms.live_security import (
    WebhookVerificationError,
    YouTubeIngestionMode,
    YouTubePollingPolicy,
    validate_meta_graph_api_version,
    validate_telegram_webhook_secret,
    verify_meta_handshake,
    verify_meta_signature,
    verify_telegram_webhook_secret,
)
from app.config import Settings
from app.domain.integrations import IntegrationReadinessState, IntegrationTarget
from app.services.integration_readiness import IntegrationReadinessService

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_meta_graph_api_version_accepts_compact_version_only() -> None:
    assert validate_meta_graph_api_version("v26.0") == "v26.0"
    for invalid in ("26.0", "v26", "v26.0/evil", "https://evil.invalid", "v0.1"):
        with pytest.raises(WebhookVerificationError):
            validate_meta_graph_api_version(invalid)


def test_meta_handshake_echoes_challenge_only_after_exact_token_match() -> None:
    challenge = "987654321"
    result = verify_meta_handshake(
        mode="subscribe",
        verify_token="configured-token",
        challenge=challenge,
        expected_verify_token="configured-token",
    )
    assert result == challenge

    with pytest.raises(WebhookVerificationError, match="mismatch"):
        verify_meta_handshake(
            mode="subscribe",
            verify_token="wrong-token",
            challenge=challenge,
            expected_verify_token="configured-token",
        )


def test_meta_signature_authenticates_raw_body_and_rejects_tampering() -> None:
    raw_body = b'{"entry":[{"id":"page-1"}]}'
    secret = "test-app-secret"
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()

    verify_meta_signature(
        raw_body=raw_body,
        signature_header=f"sha256={digest}",
        app_secret=secret,
    )

    with pytest.raises(WebhookVerificationError, match="mismatch"):
        verify_meta_signature(
            raw_body=raw_body + b" ",
            signature_header=f"sha256={digest}",
            app_secret=secret,
        )


@pytest.mark.parametrize(
    "signature",
    ["", "sha1=abc", "sha256=xyz", "sha256=00"],
)
def test_meta_signature_rejects_malformed_headers(signature: str) -> None:
    with pytest.raises(WebhookVerificationError):
        verify_meta_signature(
            raw_body=b"{}",
            signature_header=signature,
            app_secret="secret",
        )


def test_telegram_webhook_secret_contract_and_constant_time_verification() -> None:
    secret = "Gheras_webhook-Secret_2026"
    assert validate_telegram_webhook_secret(secret) == secret
    verify_telegram_webhook_secret(supplied_header=secret, expected_secret=secret)

    with pytest.raises(WebhookVerificationError, match="mismatch"):
        verify_telegram_webhook_secret(
            supplied_header="wrong",
            expected_secret=secret,
        )

    with pytest.raises(WebhookVerificationError, match="invalid characters"):
        validate_telegram_webhook_secret("not allowed!")


def test_youtube_polling_policy_uses_documented_preparation_snapshot() -> None:
    policy = YouTubePollingPolicy()
    assert policy.ingestion_mode is YouTubeIngestionMode.POLL_COMMENT_THREADS
    assert policy.max_results_per_page == 100
    assert policy.comment_list_quota_units == 1
    assert policy.reply_insert_quota_units == 50

    with pytest.raises(ValueError, match="max_results"):
        YouTubePollingPolicy(max_results_per_page=101)


def _configured_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "meta_graph_api_version": "v26.0",
        "meta_page_id": "page-id",
        "instagram_business_account_id": "ig-id",
        "telegram_supervisor_chat_id": "chat-id",
        "youtube_client_id": "client-id",
        "youtube_channel_id": "channel-id",
        "openai_api_key": "openai-test-secret",
        "meta_access_token": "meta-test-secret",
        "meta_app_secret": "meta-app-test-secret",
        "meta_verify_token": "meta-verify-test-secret",
        "telegram_bot_token": "telegram-test-secret",
        "telegram_webhook_secret": "telegram_webhook-secret",
        "youtube_client_secret": "youtube-client-test-secret",
        "youtube_refresh_token": "youtube-refresh-test-secret",
        "fatwa_bridge_secret": "fatwa-test-secret",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_readiness_reports_names_only_and_never_authorizes_live() -> None:
    settings = _configured_settings()
    results = IntegrationReadinessService(settings).evaluate_all()

    assert {result.target for result in results} == set(IntegrationTarget)
    assert all(
        result.state is IntegrationReadinessState.READY_FOR_SANDBOX_VALIDATION
        for result in results
    )
    assert all(result.live_activation_allowed is False for result in results)

    rendered = repr(results)
    for secret in (
        "openai-test-secret",
        "meta-test-secret",
        "meta-app-test-secret",
        "telegram-test-secret",
        "youtube-client-test-secret",
        "youtube-refresh-test-secret",
        "fatwa-test-secret",
    ):
        assert secret not in rendered


def test_readiness_lists_missing_variable_names_without_values() -> None:
    settings = _configured_settings(meta_access_token=None, meta_page_id="")
    result = IntegrationReadinessService(settings).evaluate(IntegrationTarget.FACEBOOK)

    assert result.state is IntegrationReadinessState.MISSING_CONFIG
    assert result.missing_variables == ("META_ACCESS_TOKEN", "META_PAGE_ID")
    assert result.invalid_variables == ()


def test_readiness_rejects_invalid_meta_version_shape() -> None:
    settings = _configured_settings(meta_graph_api_version="v26.0/unsafe")
    result = IntegrationReadinessService(settings).evaluate(IntegrationTarget.FACEBOOK)

    assert result.state is IntegrationReadinessState.INVALID_CONFIG
    assert result.invalid_variables == ("META_GRAPH_API_VERSION",)
    assert result.live_activation_allowed is False


def test_readiness_rejects_invalid_telegram_webhook_secret_shape() -> None:
    settings = _configured_settings(telegram_webhook_secret="bad secret value")
    result = IntegrationReadinessService(settings).evaluate(IntegrationTarget.TELEGRAM)

    assert result.state is IntegrationReadinessState.INVALID_CONFIG
    assert result.invalid_variables == ("TELEGRAM_WEBHOOK_SECRET",)
    assert result.live_activation_allowed is False


def test_settings_repr_hides_every_secret_bearing_value() -> None:
    settings = _configured_settings()
    rendered = repr(settings)

    hidden_values = (
        settings.openai_api_key,
        settings.meta_access_token,
        settings.meta_app_secret,
        settings.meta_verify_token,
        settings.telegram_bot_token,
        settings.telegram_webhook_secret,
        settings.youtube_client_secret,
        settings.youtube_refresh_token,
        settings.fatwa_bridge_secret,
    )
    assert all(value is not None and value not in rendered for value in hidden_values)


def test_active_branch_has_no_legacy_scheduled_runtime_artifacts() -> None:
    retired_paths = (
        PROJECT_ROOT / ".github" / "workflows" / "bot.yml",
        PROJECT_ROOT / "log.txt",
        PROJECT_ROOT / "bot_activity.log",
        PROJECT_ROOT / "seen_comments.json",
    )
    assert all(not path.exists() for path in retired_paths)

    entrypoint = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert "Legacy Facebook auto-reply runtime is retired" in entrypoint
    assert "BotManager" not in entrypoint
