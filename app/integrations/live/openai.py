"""Sandbox-only OpenAI Responses API client for structured routing evidence."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

import httpx

from app.adapters.models.contracts import (
    DecisionTask,
    StructuredDecisionRequest,
)
from app.domain.classification import ClassificationRoute
from app.domain.moderation import (
    ModerationCategory,
    ModerationSeverity,
    ModerationVerdict,
)
from app.integrations.live.activation import (
    SandboxExecutionPermit,
    require_sandbox_execution,
)
from app.integrations.live.base import ProviderProtocolError, request_json

_OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
_PROVIDER = "openai"
_OPERATION = "structured_decision"
_MAX_CREDENTIAL_LENGTH = 8192
_MAX_MODEL_ID_LENGTH = 128
_MAX_OUTPUT_TEXT_BYTES = 65_536
_MAX_JSON_DEPTH = 16
_MAX_JSON_NODES = 512
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

_MODERATION_KEYS = frozenset(
    {
        "verdict",
        "severity",
        "confidence",
        "categories",
        "text_assessed",
        "media_assessed",
    }
)
_CLASSIFICATION_KEYS = frozenset(
    {
        "proposed_route",
        "confidence",
        "religious_possible",
        "faq_key",
    }
)


def _configuration_error(reason: str) -> ProviderProtocolError:
    return ProviderProtocolError(
        provider=_PROVIDER,
        operation="configure",
        reason=reason,
    )


def _credential(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _configuration_error("missing or invalid api_key")
    if len(value) > _MAX_CREDENTIAL_LENGTH or any(ord(char) < 32 for char in value):
        raise _configuration_error("api_key exceeds allowed credential shape")
    return value


def _model_id(value: str) -> str:
    if not isinstance(value, str) or not _MODEL_ID.fullmatch(value):
        raise _configuration_error("missing or invalid model")
    if len(value) > _MAX_MODEL_ID_LENGTH:
        raise _configuration_error("model exceeds maximum length")
    return value


def _schema_for(task: DecisionTask) -> dict[str, Any]:
    if task is DecisionTask.MODERATION:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": sorted(_MODERATION_KEYS),
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": [value.value for value in ModerationVerdict],
                },
                "severity": {
                    "type": "string",
                    "enum": [value.value for value in ModerationSeverity],
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "categories": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [value.value for value in ModerationCategory],
                    },
                    "uniqueItems": True,
                    "maxItems": len(ModerationCategory),
                },
                "text_assessed": {"type": "boolean"},
                "media_assessed": {"type": "boolean"},
            },
        }
    if task is DecisionTask.CLASSIFICATION:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": sorted(_CLASSIFICATION_KEYS),
            "properties": {
                "proposed_route": {
                    "type": "string",
                    "enum": [value.value for value in ClassificationRoute],
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "religious_possible": {"type": "boolean"},
                "faq_key": {
                    "anyOf": [
                        {"type": "string", "minLength": 1, "maxLength": 128},
                        {"type": "null"},
                    ]
                },
            },
        }
    raise ProviderProtocolError(
        provider=_PROVIDER,
        operation=_OPERATION,
        reason="unsupported decision task",
    )


def _expected_keys(task: DecisionTask) -> frozenset[str]:
    if task is DecisionTask.MODERATION:
        return _MODERATION_KEYS
    if task is DecisionTask.CLASSIFICATION:
        return _CLASSIFICATION_KEYS
    raise ProviderProtocolError(
        provider=_PROVIDER,
        operation=_OPERATION,
        reason="unsupported decision task",
    )


def _input_text(request: StructuredDecisionRequest) -> str:
    if request.media:
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="media decisions are not enabled for this client",
        )
    if request.text is None or not request.text.strip():
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="decision request has no assessable text",
        )
    return request.text


def _request_body(request: StructuredDecisionRequest, *, model: str) -> dict[str, Any]:
    expected = _expected_keys(request.task)
    if frozenset(request.allowed_output_keys) != expected:
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="adapter output contract does not match provider schema",
        )
    if not request.instructions or any(not item.strip() for item in request.instructions):
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="decision instructions are missing or invalid",
        )
    text = _input_text(request)
    schema_name = f"gheras_{request.task.value}_v1"
    return {
        "model": model,
        "store": False,
        "instructions": "\n".join(request.instructions),
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            }
        ],
        "tools": [],
        "parallel_tool_calls": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": _schema_for(request.task),
            }
        },
    }


def _single_output_text(payload: Mapping[str, Any]) -> str:
    if payload.get("status") != "completed":
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="response did not complete",
        )
    output = payload.get("output")
    if not isinstance(output, list):
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="response output is missing or invalid",
        )
    messages = []
    for item in output:
        if not isinstance(item, dict):
            raise ProviderProtocolError(
                provider=_PROVIDER,
                operation=_OPERATION,
                reason="response output item is invalid",
            )
        item_type = item.get("type")
        if item_type == "reasoning":
            continue
        if item_type != "message":
            raise ProviderProtocolError(
                provider=_PROVIDER,
                operation=_OPERATION,
                reason="unexpected response output item",
            )
        messages.append(item)
    if len(messages) != 1:
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="response must contain exactly one assistant message",
        )
    message = messages[0]
    if message.get("role") != "assistant" or message.get("status") != "completed":
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="assistant message is not complete",
        )
    content = message.get("content")
    if not isinstance(content, list) or len(content) != 1:
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="assistant message content is ambiguous",
        )
    part = content[0]
    if not isinstance(part, dict) or part.get("type") != "output_text":
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="assistant output is not structured text",
        )
    text = part.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="assistant output text is missing",
        )
    if len(text.encode()) > _MAX_OUTPUT_TEXT_BYTES:
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="assistant output text exceeds maximum size",
        )
    return text


class _DuplicateJSONKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey
        result[key] = value
    return result


def _json_shape(value: object, *, depth: int = 0) -> int:
    if depth > _MAX_JSON_DEPTH:
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="structured output exceeds maximum depth",
        )
    nodes = 1
    if isinstance(value, dict):
        for child in value.values():
            nodes += _json_shape(child, depth=depth + 1)
    elif isinstance(value, list):
        for child in value:
            nodes += _json_shape(child, depth=depth + 1)
    if nodes > _MAX_JSON_NODES:
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="structured output exceeds maximum complexity",
        )
    return nodes


def _decode_structured_text(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except (_DuplicateJSONKey, json.JSONDecodeError, RecursionError):
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="structured output is not valid unique-key JSON",
        ) from None
    if not isinstance(value, dict):
        raise ProviderProtocolError(
            provider=_PROVIDER,
            operation=_OPERATION,
            reason="structured output JSON must be an object",
        )
    _json_shape(value)
    return value


class OpenAIResponsesDecisionClient:
    """Concrete sandbox client; caller must inject HTTP, permit, key, and model."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        permit: SandboxExecutionPermit | None,
        api_key: str,
        model: str,
    ) -> None:
        self._http = http
        self._permit = permit
        self._api_key = _credential(api_key)
        self._model = _model_id(model)

    def __repr__(self) -> str:
        return "OpenAIResponsesDecisionClient(provider='openai', configured=True)"

    async def request(self, request: StructuredDecisionRequest) -> object:
        require_sandbox_execution(self._permit)
        body = _request_body(request, model=self._model)
        payload = await request_json(
            http=self._http,
            permit=self._permit,
            provider=_PROVIDER,
            operation=_OPERATION,
            method="POST",
            url=_OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json_body=body,
        )
        return _decode_structured_text(_single_output_text(payload))
