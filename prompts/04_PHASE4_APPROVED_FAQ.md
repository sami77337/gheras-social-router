# Execution Prompt — Phase 4: Approved FAQ Store & Resolution Engine

Implement GitHub Issue #12 on branch `phase/04-approved-faq`, stacked on the Phase 3 classification head.

## Execution profile

- Executor class: coding agent / repository producer.
- Preferred executor when available: Codex-class coding agent.
- Prompt pattern: immutable/versioned evidence, exact-key lookup, explicit eligibility gates, fail-closed resolution, exhaustive regression tests.
- Product truth and safety invariants do not vary with executor model.

## Objective

Resolve a durable `FAQ` classification to answer text only by exact lookup of an explicitly approved, active, versioned FAQ entry. The classifier never supplies answer text.

## Hard constraints

1. No generated FAQ answer and no free-text model fallback.
2. No fuzzy/substitute key lookup.
3. No real production FAQ seed data in this phase.
4. FAQ entries are operational/non-fatwa answers only; religious rulings must remain outside this engine.
5. Missing, disabled, or invalid FAQ key fails closed to a supervisor-required resolution state.
6. No publishing and no live external API calls.
7. Persist exact provenance/version linkage for every successful FAQ resolution.
8. One durable resolution per event; duplicate/racing workers converge on one result.
9. No credentials, production logs, raw provider responses, or user payload copies.

## Store contract

Use a durable `faq_entries` store with immutable version rows. Include at least:

- id
- faq_key
- version > 0
- answer_text
- source_ref
- status: active/disabled
- approved_by
- approved_at UTC
- created_at UTC
- UNIQUE(faq_key, version)
- at most one active version per faq_key

Adding a new version is a deliberate repository operation. Do not update historical answer text in place.

## Resolution contract

Persist one `faq_resolutions` row per event, linked to:

- event_id
- classification_result_id
- exact faq_entry_id
- status: resolved / supervisor_required
- reason code
- created_at UTC

A successful resolution returns answer text from the linked approved entry. A failed resolution returns no answer text.

## Eligibility

Resolution requires a durable classification result for the event.

- route != FAQ -> ineligible, no resolution row
- route FAQ + missing/invalid key -> supervisor_required
- exact active approved entry exists -> resolved
- key absent or only disabled versions exist -> supervisor_required

## Safety note

The FAQ engine is not a religious-answer system. This phase cannot itself determine religious permissibility and must rely on the upstream classification safety gate. No production FAQ content is seeded here.

## Tests

Prove at least:

1. exact active key resolves approved answer.
2. missing key -> supervisor_required, no answer.
3. disabled key -> supervisor_required, no answer.
4. no fuzzy/substitute match.
5. non-FAQ classification is ineligible.
6. entry provenance/version are traceable.
7. historical versions remain unchanged when a new version is added.
8. at most one active version per key.
9. duplicate sequential resolution returns one durable resolution.
10. concurrent duplicate resolution produces one row.
11. all four platforms use the same FAQ resolution semantics.
12. foreign keys are enforced.
13. no production seed entries exist by default.
14. prior phase tests remain green.

## Quality gates

```bash
ruff check app tests
mypy app
pytest
```

## Promotion gate

This is a stacked phase. Prior phases require canonical closure, and this phase requires CI PASS plus independent review before promotion.
