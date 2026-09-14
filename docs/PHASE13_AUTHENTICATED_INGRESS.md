# Phase 13 — Authenticated Ingress & Collector Wiring

## Status

Implementation gate: PASS on the Phase 13 branch after Ruff, Mypy, and Pytest.

Production activation: NOT AUTHORIZED by this phase.

## Boundary

Phase 13 connects authenticated provider evidence to the existing durable inbound-event core without mounting provider routes in the default FastAPI application.

### Meta

- raw request bytes are bounded before processing;
- `X-Hub-Signature-256` is verified before JSON parsing;
- duplicate JSON object keys and pathological nesting fail closed;
- Facebook and Instagram comment envelopes normalize through the existing Phase 6 adapters;
- self-authored account comments are ignored;
- raw provider payloads are not persisted.

### Telegram

- `X-Telegram-Bot-Api-Secret-Token` is verified before JSON parsing;
- supported message evidence normalizes through the existing Telegram adapter;
- bot-authored messages are ignored;
- raw update payloads are not persisted.

### YouTube

- polling uses the Phase 12 YouTube client contract;
- comment-thread requests explicitly request `textFormat=plainText`;
- `textOriginal` is preferred when supplied by the provider, otherwise the returned plain-text display representation is preserved as received;
- self-authored channel comments are ignored;
- cross-video response evidence fails closed.

## Durable semantics

`ExactIngestionCollector` preserves Phase 1 persist-first idempotency while tightening duplicate semantics:

- identical redelivery returns the existing durable event;
- delivery-only `external_event_id` may differ across redelivery;
- reuse of the same stable provider identity with changed author/post/text/media semantics raises `IngressConflict` rather than rewriting the stored event.

Normalization stores only the provider identifiers and text required by the existing domain model. Raw webhook/update/provider response bodies are not stored.

## Activation controls

The default application does not mount provider ingress routes.

`build_ingress_router()` additionally requires an explicit `SandboxExecutionPermit`, so route construction itself fails closed when the capability is absent. Environment/configuration presence alone cannot create this capability. No production permit exists in this phase.

## Validation evidence

Final pre-documentation implementation head: `6ba7f4615061c1e8bcae6ce395f5e2d8314708e3`.

GitHub Actions run `34480298111`:

- Ruff: PASS
- Mypy: PASS
- Pytest: PASS

The suite covers authentication-before-parse, Arabic/Unicode preservation, duplicate/conflict behavior, raw-payload non-persistence, self/bot filtering, default-route absence, explicit sandbox route construction, bounded input handling, Meta/Telegram HTTP ingress behavior, and YouTube polling provenance.

## Remaining external gate

No webhook was registered, no OAuth grant was performed, no real provider credential was used, no provider API was called, and no publication occurred. Those remain outside Phase 13 and require a later explicitly governed external validation/cutover gate.
