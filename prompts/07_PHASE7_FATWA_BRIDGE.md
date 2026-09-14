# Phase 7 — Fatwa Bridge

## Objective

Implement a durable, mock-first bridge boundary for events whose authoritative classification route is `FATWA`.

## Absolute prohibition

Gheras must never generate, rewrite, summarize, infer, complete, or improve a religious ruling. A FATWA classification is routing evidence only and never contains a publishable answer.

## Request lifecycle

- exactly one durable bridge request per FATWA event;
- `pending_dispatch -> awaiting_result -> approved_result | rejected`;
- explicit `cancelled` state before a terminal result;
- failed dispatch attempts increment normalized durable metadata without raw error text.

## Approved result gate

A result is publishable later only when all are true:

- request belongs to a durable FATWA classification;
- request is in `awaiting_result`;
- external result says approved;
- non-empty answer text is supplied by the external supervised fatwa system;
- `approved_by` is present;
- `source_ref` is present;
- external result key is stable and unique.

Rejected/unapproved results must carry no answer text. Duplicate identical results are idempotent. Reuse of a result key or request with different semantics fails closed.

## Live-integration gate

Do not call, modify, stop, or redeploy `telegram-fatwa-bot-v2`. No real secret/token or production network call is allowed in this phase. The adapter contract may be defined, but only fake clients/tests may exercise it.

## Persistence

Store normalized identifiers, lifecycle state, approved external answer/provenance, and timestamps only. Never persist raw bot updates, secret headers, tokens, model prompts, or AI-generated religious text.

## Gates

- `ruff check app tests`
- `mypy app`
- `pytest`
- independent review before promotion
