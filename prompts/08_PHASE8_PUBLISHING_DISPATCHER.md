# Phase 8 — Idempotent Publishing Dispatcher

## Objective

Build a mock-first dispatcher that publishes only exact durable content already authorized by upstream evidence. It must not generate or transform reply text.

## Authoritative content sources

- FAQ: `resolved` FAQ resolution and the exact referenced FAQ entry must still be `active` at dispatch time.
- Supervisor: escalation must be `responded` and have exactly one accepted durable human response.
- FATWA: bridge request must be `approved_result` and have an attributed approved external result.

Anything else is not publishable.

## Origin publishing

Origin reply requires a non-empty `external_comment_id`. Select publisher strictly by the event's V1 platform. Publishers are injected protocols only; tests use fakes and this phase adds no production clients.

## Durable action lifecycle

Use `outbound_actions` as the pre/post external-action ledger:

- `pending`: durable intent exists, provider has not been called;
- `dispatching`: one worker atomically owns the external attempt;
- `succeeded`: stable provider result id recorded;
- `uncertain`: provider call raised after attempt began, so side effect is unknown.

Never automatically resend `dispatching`, `succeeded`, or `uncertain` actions. An `uncertain` action requires later reconciliation/human handling; blindly retrying can duplicate replies.

The deterministic idempotency key must bind event, platform, source kind, and exact source evidence id. Concurrent callers must produce at most one publisher call.

## FATWA publication policy

Represent explicit values `telegram_only`, `origin_only`, and `both`. Default is `telegram_only`. This dispatcher only handles the origin-reply side, so a FATWA result is eligible for origin publication only under `origin_only` or `both`. Changing the production policy remains a Human Gate.

## Safety

- no live APIs, tokens, OAuth, webhooks, polling, or production endpoints;
- no generated, rewritten, summarized, translated, or improved source text;
- revoked FAQ entries are blocked at dispatch time;
- no unapproved/rejected FATWA answer is exposed;
- no supervisor reply before a durable human response;
- no automatic retry after uncertain external outcome;
- no raw exception text persisted.

## Gates

- `ruff check app tests`
- `mypy app`
- `pytest`
- independent review before promotion
