# Gheras Social Router — Architecture

## Scope

V1 is a single Python service that coordinates comment handling for Facebook, Instagram, and Telegram. It keeps external integrations behind adapters and keeps the existing fatwa bot behind a narrow integration boundary.

## High-level flow

```text
Facebook ─┐
Instagram ─┼─> Collector ─> Moderation ─> Classification ─┬─> Approved FAQ reply
Telegram  ─┘                                              ├─> Human supervisor
                                                          └─> Fatwa bot bridge
```

## Boundaries

### HTTP application

FastAPI owns health endpoints and, in later phases, inbound webhook endpoints. Importing or starting the application must not require production credentials.

### Platform adapters

Facebook, Instagram, and Telegram integrations will implement adapter contracts. Domain and routing logic must not call vendor SDKs or raw HTTP endpoints directly.

### AI adapters

Moderation and classification will be separate adapters. Classification is routing-only; religious questions must never receive an AI-generated religious answer.

### Approved FAQ store

Operational answers such as schedules, registration information, and links come from an approved store. The classifier may select an intent/key but may not invent the answer.

### Fatwa bot bridge

The existing fatwa bot remains a separate system boundary. This service exchanges only the information required to route a question and publish an approved response. Public documentation should not expose unnecessary internal workflow details.

### Persistence

SQLite is the V1 persistence target, introduced behind repository/service abstractions in Phase 1. Accepted inbound events and outbound action state must survive process restarts.

## Reliability rules

- Inbound platform events are idempotent.
- Outbound replies are idempotent.
- External API failures must not silently lose accepted work.
- Low-confidence routing escalates to a human rather than guessing.
- Secrets are supplied through process environment variables and are never committed.

## Phase 0 boundary

Phase 0 intentionally contains no real Meta, Telegram, OpenAI, or fatwa-bot calls. It establishes configuration, the HTTP application, adapter interfaces, tests, and CI only.
