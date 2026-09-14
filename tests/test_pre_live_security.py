from __future__ import annotations

import ast
from pathlib import Path
from urllib.parse import urlparse

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PROJECT_ROOT / "app"
LIVE_ROOT = APP_ROOT / "integrations" / "live"

FORBIDDEN_NETWORK_IMPORT_ROOTS = {
    "aiohttp",
    "aiogram",
    "facebook_business",
    "googleapiclient",
    "httpx",
    "requests",
    "telegram",
    "urllib3",
}
LEGACY_IMPORT_ROOTS = {
    "bot_manager",
    "database_config",
    "database_manager",
}
APPROVED_LIVE_HOSTS = {
    "api.openai.com",
    "api.telegram.org",
    "graph.facebook.com",
    "www.googleapis.com",
}


def _python_files() -> list[Path]:
    return sorted(APP_ROOT.rglob("*.py"))


def _non_live_python_files() -> list[Path]:
    return [path for path in _python_files() if not path.is_relative_to(LIVE_ROOT)]


def _case_id(value: Path) -> str:
    return str(value.relative_to(PROJECT_ROOT))


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _import_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _url_literals(path: Path) -> set[str]:
    values: set[str] = set()
    for node in ast.walk(_tree(path)):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith(("http://", "https://"))
        ):
            values.add(node.value)
    return values


@pytest.mark.parametrize("path", _non_live_python_files(), ids=_case_id)
def test_network_dependencies_are_confined_to_live_boundary(path: Path) -> None:
    imported = _import_roots(path)
    assert imported.isdisjoint(FORBIDDEN_NETWORK_IMPORT_ROOTS), (
        f"{path.relative_to(PROJECT_ROOT)} imports a forbidden live-network dependency: "
        f"{sorted(imported & FORBIDDEN_NETWORK_IMPORT_ROOTS)}"
    )


@pytest.mark.parametrize("path", _python_files(), ids=_case_id)
def test_new_application_does_not_import_legacy_bot_modules(path: Path) -> None:
    imported = _import_roots(path)
    assert imported.isdisjoint(LEGACY_IMPORT_ROOTS), (
        f"{path.relative_to(PROJECT_ROOT)} imports legacy runtime code: "
        f"{sorted(imported & LEGACY_IMPORT_ROOTS)}"
    )


@pytest.mark.parametrize("path", _non_live_python_files(), ids=_case_id)
def test_hardcoded_http_endpoints_are_confined_to_live_boundary(path: Path) -> None:
    assert _url_literals(path) == set()


def test_live_boundary_uses_https_allowlisted_hosts_only() -> None:
    observed: set[str] = set()
    for path in sorted(LIVE_ROOT.rglob("*.py")):
        for value in _url_literals(path):
            parsed = urlparse(value)
            assert parsed.scheme == "https"
            assert parsed.hostname in APPROVED_LIVE_HOSTS
            observed.add(parsed.hostname or "")
    assert observed == APPROVED_LIVE_HOSTS


def test_ci_workflow_does_not_consume_production_secrets() -> None:
    ci = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "secrets." not in ci
    assert "contents: read" in ci


def test_secret_values_are_empty_in_env_example() -> None:
    env_lines = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    values = {
        key: value
        for line in env_lines
        if line and not line.startswith("#") and "=" in line
        for key, value in [line.split("=", 1)]
    }
    secret_keys = {
        "OPENAI_API_KEY",
        "META_ACCESS_TOKEN",
        "META_APP_SECRET",
        "META_VERIFY_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_SECRET",
        "YOUTUBE_CLIENT_SECRET",
        "YOUTUBE_REFRESH_TOKEN",
        "FATWA_BRIDGE_SECRET",
    }
    assert secret_keys.issubset(values)
    assert all(values[key] == "" for key in secret_keys)


def test_shadow_service_has_no_external_action_contract_imports() -> None:
    path = APP_ROOT / "services" / "shadow.py"
    text = path.read_text(encoding="utf-8")
    forbidden_symbols = {
        "ReplyPublisher",
        "SupervisorTransportAdapter",
        "FatwaBridgeAdapter",
        "PublishingRepository",
    }
    assert all(symbol not in text for symbol in forbidden_symbols)
