# Phase 5 — Durable Supervisor Workflow

## Objective

Implement the V1 human-supervisor workflow after classification/FAQ resolution. Telegram is the intended V1 transport, but this phase is mock-first and must not make live Telegram calls.

## Authoritative eligibility

An event is eligible only when either:

1. its durable classification route is `SUPERVISOR`; or
2. its durable classification route is `FAQ` and its durable FAQ resolution is `supervisor_required`.

No other event may be escalated by this service.

## Required design

- provider-neutral `SupervisorTransportAdapter` boundary;
- durable one-per-event escalation record;
- lifecycle: `pending_dispatch -> awaiting_response -> responded`, with `cancelled` available only through an explicit local action;
- one accepted durable supervisor response per escalation;
- duplicate dispatch/response handling must be idempotent;
- conflicting reuse of response idempotency keys must fail closed;
- normalized bounded supervisor reply text only; no raw Telegram update payloads;
- no automatic publication back to Facebook/Instagram/Telegram/YouTube in this phase;
- no real tokens, secrets, Telegram API calls, or production side effects.

## Persistence

Add durable tables for supervisor escalations and supervisor responses. Preserve exact source evidence linking the escalation to either a classification result or FAQ resolution.

## Safety

- AI must not fabricate a supervisor response.
- FATWA-routed events are not supervisor-workflow eligible here.
- FAQ-resolved events are not supervisor-workflow eligible.
- Telegram transport failure must not mark an escalation as dispatched/responded.
- Store only identifiers/text required for routing and later publishing.

## Quality gates

- `ruff check app tests`
- `mypy app`
- `pytest`
- independent review before promotion
