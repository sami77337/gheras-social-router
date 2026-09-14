# Execution Prompt — Phase 2: Moderation Adapter & Policy Layer

Implement GitHub Issue #8 on branch `phase/02-moderation`, which is intentionally based on the current Phase 1 head while PR #7 remains unmerged.

## Model-aware execution profile

- Executor class: coding agent / repository producer.
- Preferred executor when available: Codex-class coding agent.
- Prompt style: explicit contracts, bounded scope, deterministic acceptance tests, fail-closed ambiguity handling.
- Optimization claim: governed task decomposition only; no claim that model-specific benchmark superiority has been established for this task.
- Product truth, safety rules, and acceptance criteria are invariant across model choices.

## Read first

- `AGENTS.md`
- `README.md`
- `docs/PROJECT_SPEC_AR.md`
- `docs/ARCHITECTURE.md`
- `prompts/01_PHASE1_DURABLE_EVENTS.md`
- GitHub Issue #8

## Objective

Build the V1 moderation boundary that receives an already persisted normalized event, obtains moderation signals through a mockable async adapter, applies a deterministic policy, and stores one auditable routing-only moderation result before semantic classification.

## Hard constraints

1. No live Meta, Instagram, Telegram, YouTube/Google, OpenAI, or fatwa-bot calls.
2. No API tokens or secrets are required for tests or application import/startup.
3. Moderation must occur before semantic classification.
4. Moderation must never generate a reply, religious answer, or fatwa.
5. Uncertainty, adapter failure, malformed/insufficient evidence, or unsupported content must never silently become an allow decision.
6. This phase must not hide, delete, report, or otherwise mutate external platform content.
7. `block_routing` means only: do not continue into automated semantic routing.
8. Domain logic must remain platform-neutral across Facebook, Instagram, Telegram, and YouTube.
9. Store normalized/auditable moderation evidence only; do not persist raw provider payloads, credentials, authorization headers, or full exception traces.
10. Existing Phase 1 idempotency/state-machine guarantees must not regress.

## Required design

### Domain

Add typed moderation models with at least:

- routing disposition: `allow_routing`, `human_review`, `block_routing`
- normalized moderation categories/reason codes
- adapter assessment/signals
- persisted moderation result

The domain contract must not contain vendor-specific response objects.

### Adapter boundary

Expose a mockable async moderation protocol logically equivalent to:

```python
class ModerationAdapter(Protocol):
    async def assess(self, request: ModerationRequest) -> ModerationAssessment: ...
```

The request may contain the normalized text plus normalized media metadata already present on the durable event. It must not require raw webhook payloads.

### Deterministic policy

Implement a pure policy layer mapping normalized adapter signals to one routing-only disposition.

Minimum rules:

- adapter explicitly marks content unsafe/high severity -> `block_routing`
- uncertain, unsupported, incomplete, low-confidence, or adapter failure -> `human_review`
- only explicit sufficiently confident safe assessment -> `allow_routing`
- media that exists but was not actually assessed -> never `allow_routing`
- an event with neither assessable text nor assessed media -> `human_review`

Policy output must include machine-readable reason codes.

### Durability

Add a moderation-results persistence boundary associated with one inbound event.

Requirements:

- one active Phase 2 moderation result per event
- duplicate execution for the same event must return the same persisted result rather than creating duplicates
- foreign key to `inbound_events`
- timestamps in UTC
- no raw provider payloads
- normalized categories/reasons encoded deterministically
- persistence remains safe under normal SQLite concurrent duplicate attempts

Do not introduce a provider-specific schema.

### Service

Expose an async service logically equivalent to:

```python
await moderation_service.moderate(event_id) -> ModerationResult
```

Behavior:

1. Load durable event.
2. Return existing moderation result if already completed for that event.
3. Build normalized moderation request.
4. Await adapter assessment.
5. Convert adapter exceptions/malformed evidence into fail-closed human-review result; do not leak raw exception text into persistence.
6. Apply deterministic policy.
7. Persist result idempotently.
8. If a concurrent worker already persisted the result, return the existing result.

This service does not publish, classify, hide/delete content, or call the fatwa bridge.

## Tests

Add automated tests proving at least:

1. Explicit safe text -> `allow_routing`.
2. Explicit unsafe/high severity -> `block_routing`.
3. Ambiguous/low-confidence -> `human_review`.
4. Adapter exception -> durable `human_review` without raw exception/secret persistence.
5. Media present but unassessed -> not allowed.
6. Empty/unassessable event -> `human_review`.
7. All four V1 platforms share the same moderation service/domain semantics.
8. Duplicate calls produce one moderation row and the same result ID.
9. Concurrent duplicate moderation attempts produce one row.
10. Foreign key enforcement remains active.
11. Existing Phase 0/1 tests remain green.
12. No live credentials are needed.

## Documentation

Update `docs/ARCHITECTURE.md` to describe the moderation boundary, policy outcomes, fail-closed behavior, and the fact that external enforcement actions are out of scope for this phase.

## Quality gates

Run exactly:

```bash
ruff check app tests
mypy app
pytest
```

Do not weaken linting, typing, or prior tests.

## Promotion gate

Phase 2 implementation may be prepared and tested while Phase 1 review is pending, but it must not be promoted/merged ahead of Phase 1. Before Phase 2 promotion:

- Phase 1 must be independently accepted and merged or otherwise canonically closed.
- Phase 2 CI must pass.
- Phase 2 must receive an independent review separate from the producer.

## Out of scope

- semantic classifier implementation
- FAQ engine
- supervisor Telegram transport
- live platform adapters
- fatwa bridge
- publishing dispatcher
- external hide/delete/report actions
- production credentials

## Completion

1. Report exact code/test results.
2. Open a dependent PR referencing Issue #8.
3. Do not merge it until prerequisite and independent-review gates pass.
