# Phase 13 — Authenticated Ingress & Collector Wiring

## Objective

Connect authenticated provider input to the existing normalized, persist-first event core without activating any external integration.

## Governing rules

- Meta POST authentication is verified over the exact raw body before JSON parsing.
- Telegram webhook secret is verified before JSON parsing.
- Webhook JSON is UTF-8, bounded, object-shaped, and rejects duplicate object keys.
- Only supported V1 event shapes are normalized; unsupported/non-text/self-authored events create no durable action.
- Facebook accepts Page `feed` comment `add` events only.
- Instagram accepts `comments` events only.
- Telegram accepts ordinary text `message` updates only and ignores bot-authored messages.
- YouTube polling consumes the Phase 12 source contract and ingests supported top-level comments only.
- Provider identifiers are preserved; integer JSON identifiers are losslessly represented as decimal strings.
- Arabic/Unicode text is preserved verbatim from the selected provider field.
- Raw provider payloads are never persisted.
- Persist-first ingestion uses the existing durable repository.
- Redelivery with identical semantics is idempotent.
- Reuse of a stable event identity with changed durable semantics raises `IngressConflict`; original evidence is not rewritten.
- The default FastAPI app must not mount provider webhook routes.
- The ingress router requires explicit construction and dependency injection.
- No credential provisioning, webhook registration, OAuth grant, real provider call, or outbound publication.

## YouTube source-text rule

The client explicitly requests `textFormat=plainText`. Use `snippet.textOriginal` when the provider returns it; otherwise use `snippet.textDisplay` exactly as returned. Do not claim that `textDisplay` is the original user-authored byte-for-byte text because YouTube documents that even plain-text display text can differ from the originally posted text.

## Exit gate

- Ruff PASS.
- Mypy PASS.
- Pytest PASS.
- Authentication-before-parse tests PASS.
- Duplicate/conflict tests PASS.
- Raw-payload non-persistence test PASS.
- Default-app unmounted-route test PASS.
- No live provider network call in CI.
- Independent review remains required before promotion.
