"""Explicit execution capability for sandbox provider calls.

Environment variables cannot create this capability. Phase 12 intentionally has
no production-mode permit or automatic permit factory.
"""

from __future__ import annotations

from dataclasses import dataclass


class ExternalIntegrationDisabled(RuntimeError):
    """Raised when provider execution is attempted without an explicit permit."""


_PERMIT_MARKER = object()


@dataclass(frozen=True, slots=True, init=False)
class SandboxExecutionPermit:
    """Opaque capability proving that a caller explicitly entered sandbox validation."""

    purpose: str
    _marker: object

    def __init__(self, purpose: str, marker: object) -> None:
        if marker is not _PERMIT_MARKER:
            raise ExternalIntegrationDisabled("invalid sandbox execution permit")
        normalized = purpose.strip()
        if normalized != "sandbox_validation":
            raise ExternalIntegrationDisabled("unsupported external execution purpose")
        object.__setattr__(self, "purpose", normalized)
        object.__setattr__(self, "_marker", marker)


def issue_sandbox_execution_permit(*, purpose: str) -> SandboxExecutionPermit:
    """Issue a sandbox-only capability after an explicit code-level action."""

    return SandboxExecutionPermit(purpose, _PERMIT_MARKER)


def require_sandbox_execution(permit: SandboxExecutionPermit | None) -> SandboxExecutionPermit:
    """Fail before request construction when the explicit capability is absent."""

    if permit is None or permit._marker is not _PERMIT_MARKER:
        raise ExternalIntegrationDisabled("sandbox execution permit is required")
    return permit
