import pytest

from app.config import Settings


SECRET_ENV_VARS = (
    "OPENAI_API_KEY",
    "META_ACCESS_TOKEN",
    "META_APP_SECRET",
    "META_VERIFY_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "FATWA_BRIDGE_SECRET",
)


def test_settings_start_without_external_credentials(monkeypatch) -> None:
    for variable in SECRET_ENV_VARS:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("APP_ENV", "test")

    settings = Settings.from_env()

    assert settings.environment == "test"
    assert settings.openai_api_key is None
    assert settings.meta_access_token is None
    assert settings.telegram_bot_token is None


def test_secrets_are_loaded_from_environment_and_hidden_from_repr(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-value")

    settings = Settings.from_env()

    assert settings.openai_api_key == "test-secret-value"
    assert "test-secret-value" not in repr(settings)


def test_invalid_environment_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "invalid")

    with pytest.raises(ValueError, match="APP_ENV"):
        Settings.from_env()
