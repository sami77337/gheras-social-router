"""Explicitly constructed authenticated ingress router; unmounted by default."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import PlainTextResponse

from app.adapters.platforms.live_security import (
    WebhookVerificationError,
    verify_meta_handshake,
)
from app.ingress.common import (
    MAX_WEBHOOK_BODY_BYTES,
    IngressBatchResult,
    IngressConflict,
    IngressPayloadError,
)
from app.ingress.meta import MetaWebhookIngress
from app.ingress.telegram import TelegramWebhookIngress
from app.integrations.live.activation import (
    SandboxExecutionPermit,
    require_sandbox_execution,
)


@dataclass(frozen=True, slots=True)
class IngressRuntime:
    """Explicit dependencies required to construct inbound webhook routes."""

    meta: MetaWebhookIngress
    telegram: TelegramWebhookIngress
    meta_verify_token: str

    def __post_init__(self) -> None:
        if not isinstance(self.meta_verify_token, str) or not self.meta_verify_token:
            raise ValueError("Meta verify token must not be empty")


def _summary(batch: IngressBatchResult) -> dict[str, int]:
    return {
        "accepted": batch.accepted_count,
        "created": batch.created_count,
        "duplicates": batch.duplicate_count,
        "ignored": batch.ignored_count,
    }


def _require_json_content_type(request: Request) -> None:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="application/json is required",
        )


async def _bounded_body(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="webhook body exceeds maximum size",
            )
    return bytes(body)


def _translate_ingress_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WebhookVerificationError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid webhook authentication",
        )
    if isinstance(exc, IngressConflict):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ingress identity conflict",
        )
    if isinstance(exc, IngressPayloadError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid ingress payload",
        )
    raise exc


def build_ingress_router(
    runtime: IngressRuntime,
    *,
    permit: SandboxExecutionPermit | None = None,
) -> APIRouter:
    """Build sandbox ingress routes only after explicit capability issuance."""

    require_sandbox_execution(permit)
    router = APIRouter(prefix="/integrations", tags=["integrations"])

    @router.get("/meta/webhook", response_class=PlainTextResponse)
    async def meta_verify(request: Request) -> PlainTextResponse:
        try:
            challenge = verify_meta_handshake(
                mode=request.query_params.get("hub.mode", ""),
                verify_token=request.query_params.get("hub.verify_token", ""),
                challenge=request.query_params.get("hub.challenge", ""),
                expected_verify_token=runtime.meta_verify_token,
            )
        except WebhookVerificationError as exc:
            raise _translate_ingress_error(exc) from None
        return PlainTextResponse(challenge)

    @router.post("/meta/webhook")
    async def meta_webhook(request: Request) -> dict[str, int]:
        _require_json_content_type(request)
        body = await _bounded_body(request)
        try:
            batch = runtime.meta.ingest(
                raw_body=body,
                signature_header=request.headers.get("x-hub-signature-256", ""),
            )
        except (WebhookVerificationError, IngressPayloadError, IngressConflict) as exc:
            raise _translate_ingress_error(exc) from None
        return _summary(batch)

    @router.post("/telegram/webhook")
    async def telegram_webhook(request: Request) -> dict[str, int]:
        _require_json_content_type(request)
        body = await _bounded_body(request)
        try:
            batch = runtime.telegram.ingest(
                raw_body=body,
                secret_header=request.headers.get(
                    "x-telegram-bot-api-secret-token",
                    "",
                ),
            )
        except (WebhookVerificationError, IngressPayloadError, IngressConflict) as exc:
            raise _translate_ingress_error(exc) from None
        return _summary(batch)

    return router
