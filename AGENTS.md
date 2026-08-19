# AGENTS.md

## Mission

Build the production-ready Gheras Social Comment Router for Facebook, Instagram, and Telegram while preserving a clean integration boundary with the existing Telegram fatwa bot.

## Non-negotiable product rules

1. AI must never generate or deliver a religious ruling/fatwa as an automated answer.
2. If a comment may be religious and classification confidence is insufficient, route it to the fatwa path.
3. FAQ replies must come from an approved-answer store. The model may classify intent, but must not invent dates, URLs, registration status, schedules, or policy information.
4. Unknown or low-confidence non-religious questions must be escalated to human supervisors.
5. Moderation happens before semantic routing.
6. All inbound events and outbound actions must be idempotent.
7. Never commit API keys, access tokens, webhook secrets, Telegram tokens, database dumps, user data, or production logs.
8. X/Twitter is out of scope for V1.
9. Publishing after a textual fatwa answer supports: Telegram only (default), original comment only, or both.
10. Do not expose unnecessary internal fatwa workflow details in public-facing documentation or UI.

## Engineering constraints

- Python 3.12.
- Prefer FastAPI for webhooks and HTTP endpoints.
- Prefer aiogram for Telegram integration.
- Use async I/O for network operations.
- Use typed models and structured validation.
- V1 database: SQLite behind a repository/service abstraction so PostgreSQL can be introduced later.
- Use `httpx` for external HTTP calls.
- Use `pytest` for automated tests.
- External API code must be behind adapters/interfaces and mockable in tests.
- Processing state must survive restarts; do not use memory-only queues as the source of truth.
- Add retry/backoff only where operations are safe and idempotent.
- Log correlation IDs, not secrets or full sensitive payloads.

## Delivery workflow

- Work on `codex/v1-full-build` unless a phase-specific branch is requested.
- Implement one phase at a time.
- Each phase must include tests and documentation changes.
- Do not refactor unrelated legacy code unless required by the current phase.
- Before marking a phase complete, run the full test suite and report exact commands/results.
- Do not merge to `main` without review.

## Initial phase order

1. Bootstrap and project structure.
2. Durable event model, database, processing states, idempotency.
3. Moderation adapter and policy layer.
4. GPT-5.6 Luna classifier with strict structured output.
5. Approved FAQ engine.
6. Telegram supervisor flow.
7. Meta adapter for Facebook and Instagram webhooks/comments.
8. Fatwa-bot integration bridge.
9. Publishing dispatcher.
10. Evaluation, shadow mode, security review, regression audit.

## Definition of done for V1

- Duplicate webhook events do not cause duplicate replies.
- Restarts do not lose accepted events.
- OpenAI/API failures result in retry or human escalation, never silent loss.
- FAQ answers are traceable to an approved entry.
- Religious questions are never answered automatically by AI.
- Replies are delivered to the correct original platform/comment.
- Shadow-mode evaluation is completed before enabling broad auto-reply.
- CI and all automated tests pass.
