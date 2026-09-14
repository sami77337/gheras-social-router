# Phase 9 — Shadow Mode Evaluation & Audit

## Scope

Implement side-effect-free evaluation over durable Gheras evidence. Shadow Mode observes what the current system would do; it does not perform the action.

## Absolute constraints

- No live API calls, credentials, OAuth, webhooks, polling, or production endpoints.
- Do not call `ReplyPublisher`, supervisor transport, FATWA bridge transport, or any platform network client.
- Do not create, claim, update, or reconcile `outbound_actions`.
- Do not transition `inbound_events` processing state.
- Do not generate, rewrite, summarize, translate, complete, or improve any reply text.
- AI must never generate a fatwa.
- Moderation remains authoritative and precedes semantic routing.

## Allowed durable inputs

- inbound event identity and processing metadata;
- moderation result;
- classification result;
- approved FAQ resolution and exact active entry;
- supervisor escalation and accepted human response;
- supervised FATWA bridge request/result;
- configured FATWA publication policy.

## Outcomes

- `would_publish`
- `would_wait_human`
- `would_route_fatwa`
- `not_ready`
- `blocked`

Only `would_publish` may carry source kind, exact evidence id, and proposed text. That proposed text must be copied verbatim from already-authorized durable evidence.

## Persistence

Store one immutable `shadow_evaluations` row per `(event_id, evaluator_version)`. Duplicate/concurrent identical evaluations converge on one row. Reuse of the same key with different semantics is a conflict and fails closed.

Persist normalized audit fields only. Never persist raw provider payloads, prompts, chain-of-thought, tokens, headers, or transport diagnostics.

## Reporting

Aggregate reports may expose counts by platform, route, and outcome plus publishable/non-publishable totals. Aggregate reports must not expose user message/reply content.

## Required tests

- approved active FAQ -> `would_publish` exact FAQ text;
- revoked FAQ -> `blocked`;
- supervisor pending -> `would_wait_human`;
- supervisor responded -> `would_publish` exact human response;
- FATWA pending/awaiting -> `would_route_fatwa`;
- approved FATWA under default `telegram_only` -> no origin publication;
- explicit origin FATWA policy -> `would_publish` exact approved external text;
- moderation human review/block precedes classification;
- all four V1 platforms;
- duplicate and concurrent evaluation idempotency;
- evaluator-version semantic conflict fails closed;
- restart durability;
- event processing state remains unchanged;
- `outbound_actions` count remains unchanged;
- aggregate report contains no proposed text.

## Gates

Run:

```bash
ruff check app tests
mypy app
pytest
```

Do not promote to `main`. Open a stacked PR against Phase 8 and perform an independent adversarial review before any promotion.
