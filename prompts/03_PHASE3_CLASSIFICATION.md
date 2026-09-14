# Execution Prompt — Phase 3: Structured Routing Classifier

Implement GitHub Issue #10 on branch `phase/03-classification`, stacked on the Phase 2 moderation head.

## Model-aware execution profile

- Executor class: coding agent / repository producer.
- Preferred executor when available: Codex-class coding agent.
- Prompt shape: explicit typed contracts, deterministic local safety policy, provider isolation, exhaustive fail-closed tests.
- No model-specific optimization claim is made beyond governed prompt structure; product truth and safety invariants are fixed regardless of executor model.

## Read first

- `AGENTS.md`
- `docs/PROJECT_SPEC_AR.md`
- `docs/ARCHITECTURE.md`
- `prompts/02_PHASE2_MODERATION.md`
- GitHub Issue #10

## Objective

Build a provider-neutral, mock-first semantic routing classifier that runs only after a durable `allow_routing` moderation result and produces exactly one of three routes:

- `FAQ`
- `SUPERVISOR`
- `FATWA`

The classifier selects a route and optional FAQ key only. It never creates user-facing answer text.

## Hard safety constraints

1. AI must never generate or deliver a religious ruling/fatwa.
2. If content may be religious, local policy must prefer `FATWA` over FAQ/SUPERVISOR whenever uncertainty exists.
3. Low-confidence non-religious FAQ candidates become `SUPERVISOR`.
4. FAQ is valid only with a compact intent/key for a later approved-answer store.
5. Model/provider free text must never control execution directly.
6. Malformed adapter results or adapter failures become a durable non-automatic route; never FAQ.
7. Classification is forbidden unless durable moderation disposition is `allow_routing`.
8. No real OpenAI, Meta, Telegram, YouTube/Google, or fatwa-bot calls in this phase.
9. Persist normalized routing evidence only, never raw model responses, credentials, auth headers, chain-of-thought, or full provider payloads.
10. One durable classification result per inbound event; duplicate/racing executions are idempotent.

## Domain contract

Add typed provider-neutral models for:

- classification route enum
- normalized adapter assessment
- deterministic policy decision/reason codes
- persisted classification result

The adapter assessment should contain only fields necessary for routing, such as:

- proposed route
- confidence in [0,1]
- `religious_possible` boolean
- optional `faq_key`

Do not store answer text.

## Adapter boundary

Expose a mockable async protocol logically equivalent to:

```python
class ClassificationAdapter(Protocol):
    async def classify(self, request: ClassificationRequest) -> ClassificationAssessment: ...
```

Adapter identity/version must be auditable. The request is built from the normalized durable event, not raw platform payloads.

## Deterministic policy

Minimum rules:

- `religious_possible=True` => route `FATWA` regardless of an adapter proposal for FAQ/SUPERVISOR.
- explicit FATWA proposal => `FATWA`.
- explicit SUPERVISOR proposal => `SUPERVISOR`.
- FAQ proposal below configured minimum confidence => `SUPERVISOR`.
- FAQ proposal without a valid compact `faq_key` => `SUPERVISOR`.
- sufficiently confident FAQ proposal with valid key and no religious signal => `FAQ`.
- adapter failure/malformed assessment => `SUPERVISOR`.

The local policy is authoritative; the provider proposal is evidence only.

## Durability

Add a `classification_results` table with one row per event and normalized fields only. Include:

- id
- event_id unique FK
- route
- reason code(s)
- faq_key nullable
- religious_possible
- confidence nullable
- adapter_name/version
- created_at UTC

No raw model response column.

## Service

Expose an async service logically equivalent to:

```python
await classification_service.classify(event_id) -> ClassificationResult
```

Behavior:

1. Return existing durable result if present.
2. Verify the event has a durable moderation result.
3. Refuse classification unless moderation is `allow_routing`.
4. Load the normalized inbound event.
5. Call the async adapter.
6. Convert adapter failure/malformed evidence to a normalized fail-closed decision.
7. Apply local policy.
8. Persist idempotently and return the winner of duplicate races.

No publishing, FAQ lookup, supervisor transport, or fatwa-bot call in this phase.

## Tests

Prove at least:

1. confident FAQ + valid key => FAQ.
2. low-confidence FAQ => SUPERVISOR.
3. FAQ without key => SUPERVISOR.
4. `religious_possible=True` overrides FAQ to FATWA.
5. explicit FATWA => FATWA.
6. explicit SUPERVISOR => SUPERVISOR.
7. adapter failure => durable SUPERVISOR without raw exception secret persistence.
8. malformed adapter result => SUPERVISOR.
9. classification cannot run when moderation is absent/human-review/block-routing.
10. all four V1 platforms use the same classification semantics.
11. duplicate sequential calls return one result and avoid repeat adapter execution.
12. concurrent duplicate calls produce one row.
13. SQLite FK enforcement remains active.
14. no answer text or raw provider payload is stored.
15. all existing Phase 0/1/2 tests remain green.

## Quality gates

Run:

```bash
ruff check app tests
mypy app
pytest
```

## Promotion gate

This is a stacked phase. Do not promote it ahead of Phase 1/2 canonical closure. It also requires its own independent review and CI PASS before promotion.

## Out of scope

- approved FAQ answer retrieval
- supervisor transport
- live OpenAI call
- platform adapters
- fatwa-bot bridge
- publishing
- production credentials
