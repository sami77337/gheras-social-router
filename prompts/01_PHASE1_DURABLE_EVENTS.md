# Codex Task — Phase 1: Durable Events, SQLite & Idempotency

Implement GitHub Issue #6 on branch `codex/v1-full-build`.

## Read first

- `AGENTS.md`
- `README.md`
- `docs/PROJECT_SPEC_AR.md`
- `docs/ARCHITECTURE.md`
- GitHub Issue #6

## Scope

Build only the durable processing core. Do not add live Meta, Telegram, OpenAI, or fatwa-bot calls in this phase.

## Required architecture

Use a small layered structure, for example:

```text
app/
  domain/
    events.py
    states.py
  persistence/
    sqlite.py
    schema.py
    repositories.py
  services/
    ingestion.py
    transitions.py
```

Equivalent organization is acceptable if boundaries remain clear.

## Domain requirements

### Platform

Allowed values:

- `facebook`
- `instagram`
- `telegram`

### Processing states

At minimum:

- `received`
- `processing`
- `waiting_human`
- `completed`
- `failed_retryable`
- `failed_terminal`

Create an explicit transition table. Do not allow arbitrary status mutation.

Recommended transition behavior:

- `received -> processing`
- `processing -> completed`
- `processing -> waiting_human`
- `processing -> failed_retryable`
- `processing -> failed_terminal`
- `failed_retryable -> processing`
- `waiting_human -> processing`
- `waiting_human -> completed`

Terminal `completed` and `failed_terminal` must not transition without an explicit future recovery mechanism.

## SQLite schema

### inbound_events

Persist normalized fields only. Include at least:

- `id` UUID text primary key
- `platform`
- `external_event_key`
- `external_event_id`
- `external_comment_id`
- `external_post_id`
- `author_id`
- `text`
- `media_json`
- `correlation_id`
- `status`
- `retry_count`
- `next_retry_at`
- `created_at`
- `updated_at`

Enforce unique `(platform, external_event_key)`.

### processing_attempts

Include at least:

- `id`
- `event_id`
- `attempt_number`
- `started_at`
- `finished_at`
- `outcome`
- sanitized `error_code`
- sanitized `error_message`

Do not persist API keys, authorization headers, full exception traces, or raw webhook payloads.

### outbound_actions

Include at least:

- `id`
- `event_id`
- `platform`
- `action_type`
- `idempotency_key`
- `status`
- `external_result_id`
- `created_at`
- `updated_at`

Enforce unique `idempotency_key`.

## Persistence rules

- Enable SQLite foreign keys.
- Prefer WAL mode for V1 where safe.
- Configure a sensible busy timeout.
- Use parameterized SQL.
- Keep connection handling explicit and testable.
- No global long-lived mutable connection shared unsafely across threads.
- All timestamps UTC.

## Ingestion semantics

Expose a service method logically equivalent to:

```python
ingest_event(normalized_event) -> IngestionResult
```

Behavior:

1. Begin DB operation.
2. Insert event if unique key has not been seen.
3. If duplicate, fetch and return existing event.
4. Never create two records for the same platform + external event key.
5. Return whether the event was newly created.

The implementation must remain correct when duplicate insert attempts race under normal SQLite V1 concurrency.

## Tests

Add tests proving:

1. New DB initializes correctly.
2. First event insert succeeds.
3. Same event inserted 100 times results in one row.
4. Duplicate calls return the same internal event ID.
5. Invalid state transitions raise a deterministic domain error.
6. Valid transitions persist.
7. A file-backed temp DB retains events after repository/service recreation.
8. Duplicate outbound idempotency keys cannot create two actions.
9. Processing attempts are stored and increment correctly.
10. SQLite foreign keys are active.
11. Concurrent duplicate ingestion does not produce duplicates.

## Quality gates

Run and report:

```bash
ruff check .
mypy app
pytest
```

Do not weaken existing Phase 0 tests or lint/type configuration just to make this phase pass.

## Documentation

Update `docs/ARCHITECTURE.md` with the durable event boundary and persist-first rule. Keep documentation high-level and do not expose unnecessary fatwa workflow internals.

## Out of scope

- Moderation implementation
- GPT-5.6 Luna calls
- FAQ routing
- Telegram supervisor flow
- Meta webhooks
- fatwa bridge
- live outbound publishing
- Redis/Celery/Kafka

## Completion

When done:

1. Summarize schema and state-machine decisions.
2. Report exact test/lint/type commands and counts.
3. Open a PR to `main` referencing and closing Issue #6.
4. Do not merge the PR yourself.
