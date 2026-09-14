"""Shared sandbox HTTP boundary with strict host and error redaction rules."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from app.integrations.live.activation import SandboxExecutionPermit, require_sandbox_execution

APPROVED_PROVIDER_HOSTS = frozenset(
    {
        "api.openai.com",
        "api.telegram.org",
        "graph.facebook.com",
        "www.googleapis.com",
    }
)
_MAX_RESPONSE_BYTES = 1_000_000


class ProviderIntegrationError(RuntimeError):
    """Base provider error that deliberately excludes URL/body/credential data."""


class ProviderTransportError(ProviderIntegrationError):
    def __init__(self, *, provider: str, operation: str) -> None:
        self.provider = provider
        self.operation = operation
        super().__init__(f"{provider} transport failure during {operation}")


class ProviderHTTPError(ProviderIntegrationError):
    def __init__(
        self,
        *,
        provider: str,
        operation: str,
        status_code: int,
        retryable: bool,
    ) -> None:
        self.provider = provider
        self.operation = operation
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(
            f"{provider} HTTP {status_code} during {operation}; retryable={retryable}"
        )


class ProviderProtocolError(ProviderIntegrationError):
    def __init__(self, *, provider: str, operation: str, reason: str) -> None:
        self.provider = provider
        self.operation = operation
        self.reason = reason
        super().__init__(f"{provider} protocol failure during {operation}: {reason}")


def ensure_approved_url(url: str) -> httpx.URL:
    """Require HTTPS and one exact allowlisted provider hostname."""

    parsed = httpx.URL(url)
    if parsed.scheme != "https":
        raise ProviderProtocolError(
            provider="boundary",
            operation="validate_url",
            reason="HTTPS is required",
        )
    if parsed.host not in APPROVED_PROVIDER_HOSTS:
        raise ProviderProtocolError(
            provider="boundary",
            operation="validate_url",
            reason="provider host is not allowlisted",
        )
    if parsed.port is not None:
        raise ProviderProtocolError(
            provider="boundary",
            operation="validate_url",
            reason="non-default provider port is forbidden",
        )
    if parsed.userinfo:
        raise ProviderProtocolError(
            provider="boundary",
            operation="validate_url",
            reason="userinfo in provider URL is forbidden",
        )
    if parsed.fragment:
        raise ProviderProtocolError(
            provider="boundary",
            operation="validate_url",
            reason="provider URL fragment is forbidden",
        )
    return parsed


def _retryable_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code <= 599


async def request_json(
    *,
    http: httpx.AsyncClient,
    permit: SandboxExecutionPermit | None,
    provider: str,
    operation: str,
    method: str,
    url: str,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str | int] | None = None,
    data: Mapping[str, str] | None = None,
    json_body: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Execute one explicitly permitted request and return a bounded JSON object."""

    require_sandbox_execution(permit)
    approved_url = ensure_approved_url(url)
    request = http.build_request(
        method,
        approved_url,
        headers=headers,
        params=params,
        data=data,
        json=json_body,
    )
    try:
        response = await http.send(request, follow_redirects=False)
    except httpx.HTTPError:
        raise ProviderTransportError(provider=provider, operation=operation) from None

    if response.status_code >= 400:
        raise ProviderHTTPError(
            provider=provider,
            operation=operation,
            status_code=response.status_code,
            retryable=_retryable_status(response.status_code),
        )
    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise ProviderProtocolError(
            provider=provider,
            operation=operation,
            reason="response exceeds maximum size",
        )

    try:
        payload = response.json()
    except ValueError:
        raise ProviderProtocolError(
            provider=provider,
            operation=operation,
            reason="response is not valid JSON",
        ) from None
    if not isinstance(payload, dict):
        raise ProviderProtocolError(
            provider=provider,
            operation=operation,
            reason="response JSON must be an object",
        )
    return payload


def required_response_id(
    payload: Mapping[str, Any],
    *,
    provider: str,
    operation: str,
    field: str = "id",
) -> str:
    """Extract a stable provider id without including payload data in errors."""

    value = payload.get(field)
    if not isinstance(value, str) or not value.strip() or any(char.isspace() for char in value):
        raise ProviderProtocolError(
            provider=provider,
            operation=operation,
            reason=f"missing or invalid {field}",
        )
    if len(value) > 512:
        raise ProviderProtocolError(
            provider=provider,
            operation=operation,
            reason=f"{field} exceeds maximum length",
        )
    return value
