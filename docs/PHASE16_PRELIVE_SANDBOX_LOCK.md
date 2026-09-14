# Phase 16 — Pre-Live Sandbox Composition Lock

## Status

**ENGINEERING / SANDBOX READINESS: PASS**  
**LIVE PRODUCTION ACTIVATION: HOLD**

Phase 16 completes the pre-live composition layer without enabling production execution.

## Locked scope

### Structured OpenAI decision client

- Uses the Responses API boundary through injected `httpx.AsyncClient` only.
- Requires an explicit `SandboxExecutionPermit`.
- Uses strict structured JSON-schema output.
- Sets `store: false`.
- Exposes no answer/reply/FATWA generation surface.
- Rejects refusal, incomplete/failed output, ambiguous assistant output, malformed JSON, duplicate JSON keys, unsupported media claims, and provider errors fail-closed.
- Redacts provider URL/body/credential details from raised integration errors.

### Explicit pre-live composition

`PreLiveSandboxRuntime` composes durable ingestion, moderation, classification, approved FAQ, supervisor workflow, FATWA bridge state, Shadow evaluation, publishing, and authenticated ingress over SQLite.

The runtime:

- requires an explicit sandbox permit before construction;
- does not mount provider routes in the default FastAPI application;
- does not auto-dispatch any provider publication;
- keeps publication as an explicit separate operation;
- keeps FATWA generation outside Gheras;
- retains the safe default FATWA publication policy.

### Durable human moderation review / resume

Machine moderation evidence remains immutable.

A `human_review` disposition now creates a separate durable `moderation_human_reviews` record with:

- one review per event;
- one review per moderation result;
- `pending -> resolved` lifecycle;
- explicit `allow_routing` or `block_routing` human decision;
- bounded reviewer reference;
- stable external review key for idempotency;
- conflict detection for contradictory reuse.

Classification remains blocked while the review is pending. A resolved `allow_routing` review permits classification without rewriting the original machine moderation result. A resolved `block_routing` review remains blocked.

Pending review state is represented by the durable review record and does not consume the immutable Shadow `(event, evaluator_version)` slot. The first persisted Shadow observation is therefore made after review resolution.

### Publication defense in depth

The pre-live publishing boundary re-checks effective moderation permission before resolving any publishable content.

Even if contradictory classification evidence is introduced outside the normal service path, publication fails closed unless:

- machine moderation is `allow_routing`; or
- machine moderation is `human_review` and the durable human review is resolved as `allow_routing`.

## Validation evidence

Pre-lock GitHub Actions run `34602019880` on head `6af309170c3a7068876e86f65d8abcf789b2fdb4`:

- Ruff — PASS
- Mypy — PASS
- Pytest — PASS

The regression suite includes:

- sandbox permit gating;
- OpenAI strict request/response handling and redaction;
- no default provider ingress mounting;
- no automatic publication;
- human moderation pending stop;
- allow review resume after SQLite restart;
- block review no-classification behavior;
- review idempotency and conflict detection;
- original machine moderation evidence preservation;
- publication rejection behind unresolved moderation review;
- FAQ/SUPERVISOR/FATWA safety behavior.

## Explicit non-claims / remaining Human Gates

This lock does **not** claim production readiness in the external-provider sense. The following remain outside Phase 16 and must stay HOLD until validated:

1. independent submitted review of the stacked implementation chain;
2. promotion/merge of the reviewed stack to `main`;
3. production/sandbox provider credentials and scope validation outside Git/chat;
4. real Facebook/Instagram/Telegram/YouTube provider-side validation;
5. real supervised FATWA-system connection and reconciliation validation;
6. dependency/SCA assessment and production lock/pinning strategy;
7. staging Shadow Mode evidence using representative external/safely replayed data;
8. production database/backups, monitoring, alerting, ingress controls, reconciliation, and rollback/cutover procedure;
9. final controlled live activation.

No production credential, OAuth grant, webhook registration, real provider API call, FATWA generation, or live publication is authorized or performed by this lock.
