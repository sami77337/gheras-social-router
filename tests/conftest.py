from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import APIRouter

from app.api.integrations import IngressRuntime
from app.api.integrations import build_ingress_router as _build_ingress_router
from app.integrations.live.activation import issue_sandbox_execution_permit


@pytest.fixture(autouse=True)
def _phase13_authenticated_ingress_router_harness(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Inject sandbox capability only into the Phase 13 HTTP-router test module."""

    if request.module.__name__.endswith("test_authenticated_ingress"):

        def _sandbox_router(runtime: IngressRuntime) -> APIRouter:
            return _build_ingress_router(
                runtime,
                permit=issue_sandbox_execution_permit(purpose="sandbox_validation"),
            )

        monkeypatch.setattr(request.module, "build_ingress_router", _sandbox_router)

    yield
