# Gheras Social Router — Architecture

## Scope

V1 is a single Python service that coordinates comment/message handling for Facebook, Instagram, Telegram, and YouTube. External integrations stay behind adapters, and the supervised FATWA system remains behind a narrow integration boundary.

## High-level flow

```text
Facebook  ─┐
Instagram ─┤
Telegram  ─┼─> Collector ─> Persist First ─> Moderation ─> Classification ─┬─> FAQ
YouTube   ─┘                                                                ├─> Supervisor
                                                                            └─> Fatwa Bridge
                                                                                     │
                                                                                     ▼
                                                                            Publishing Dispatcher
                                                                                     │
                                                            ┌────────────┬────────────┼───────────┐
                                                            ▼            ▼            ▼           ▼
                                                         Facebook     Instagram    Telegram    YouTube
```

Shadow Mode observes the same durable decision evidence in a separate read/audit path and performs no publication or transport action.

## Boundaries

### HTTP application

FastAPI owns health endpoints and, in later phases, authenticated inbound webhook endpoints. Importing or starting the application must not require production credentials or create network side effects.

### Platform adapters

Facebook, Instagram, Telegram, and YouTube integrations implement provider-specific adapter modules while domain/services remain provider-neutral.

Phase 6 implements pure normalization plus injected client protocols. Stable inbound identities are normalized as follows:

- Facebook: comment id.
- Instagram: comment id.
- Telegram: `chat_id:message_id`; update id remains delivery metadata.
- YouTube: comment id; thread id may be retained separately.

Adapters preserve Arabic/Unicode text verbatim and fail closed when required identifiers or text are missing. Reply publishers and the Telegram supervisor transport delegate only to injected client protocols. Raw provider payloads are not persisted.

### Durable event boundary

Every accepted inbound event is persisted before moderation, classification, FAQ resolution, supervisor handling, fatwa routing, or publishing work begins.

The SQLite durable layer contains persistent concerns including:

- `inbound_events`: normalized accepted events and processing state.
- `processing_attempts`: sanitized attempt history and retry metadata.
- `outbound_actions`: durable publish intents/results with unique idempotency keys.
- `moderation_results`: one normalized moderation decision per event.
- `classification_results`: one normalized semantic route per eligible event.
- `faq_entries`: immutable versioned approved operational answers.
- `faq_resolutions`: one exact-key FAQ resolution per classified event.
- `supervisor_escalations`: one durable human escalation per eligible event.
- `supervisor_responses`: one accepted human response per escalation.
- `fatwa_bridge_requests`: one durable supervised-fatwa request per FATWA event.
- `fatwa_bridge_results`: one normalized attributed external result per bridge request.
- `shadow_evaluations`: immutable side-effect-free observations keyed by event and evaluator version.

Inbound uniqueness is `(platform, external_event_key)`. Outbound uniqueness is `idempotency_key`. Duplicate work must resolve to the existing durable record instead of creating a second semantic action.

### Processing state machine

Core event state changes are explicit domain transitions. V1 includes:

- `received`
- `processing`
- `waiting_human`
- `completed`
- `failed_retryable`
- `failed_terminal`

Terminal states do not transition unless a future explicit recovery mechanism is introduced.

### Moderation boundary

Moderation occurs after persist-first ingestion and before semantic classification.

A provider-neutral async `ModerationAdapter` returns normalized evidence only. A deterministic local policy maps the evidence to one routing-only disposition:

- `allow_routing`
- `human_review`
- `block_routing`

`block_routing` does not authorize hide/delete/report actions. Missing coverage, low confidence, malformed evidence, contradictory evidence, and adapter failure fail closed toward human review rather than automatic routing.

### Classification boundary

Classification runs only after durable `allow_routing` moderation. The async adapter produces routing evidence only; the deterministic local policy is authoritative.

The only V1 routes are:

- `FAQ`
- `SUPERVISOR`
- `FATWA`

Safety rules include:

- `religious_possible=true` always forces `FATWA`.
- an explicit FATWA proposal remains `FATWA`.
- low-confidence FAQ becomes `SUPERVISOR`.
- FAQ without a valid compact key becomes `SUPERVISOR`.
- adapter failure/malformed output becomes `SUPERVISOR`.
- the classifier never generates user-facing answer text or a fatwa.

`classification_results` deliberately stores no prompt, chain-of-thought, raw provider response, or answer payload.

### Approved FAQ boundary

FAQ resolution is eligible only for a durable `FAQ` classification containing an exact key.

The model never supplies the answer. Answers come only from `faq_entries`, which are versioned and preserve approval provenance (`approved_by`, `approved_at`, `source_ref`). Historical versions are not rewritten in place, and SQLite permits at most one active version for a key.

Resolution is exact-key only; no fuzzy key substitution and no generated fallback are allowed. Missing, disabled, or invalid keys create `supervisor_required` resolution instead of answer text.

Each `faq_resolution` links the event and classification to the exact approved entry used. Duplicate/racing workers converge on one resolution. If an entry is later disabled, the historical resolution remains auditable but its answer text is no longer eligible for future publishing.

### Human supervisor boundary

Human escalation is eligible only when classification is explicitly `SUPERVISOR`, or a `FAQ` classification has a durable `supervisor_required` FAQ resolution.

FATWA-routed events and successfully resolved FAQ events are not eligible for this workflow. Telegram is the intended V1 supervisor transport, but transport is not the source of truth; SQLite holds escalation and response state.

The escalation lifecycle is:

```text
pending_dispatch -> awaiting_response -> responded
       │                  │
       └──────────────> cancelled
```

One accepted human response is allowed per escalation. Duplicate identical provider updates are idempotent; conflicting response or transport evidence fails closed.

### FATWA bridge

A `FATWA` classification is only a routing decision and never contains a religious answer. Gheras cannot generate, rewrite, summarize, infer, complete, or improve a fatwa.

Phase 7 adds a durable bridge boundary to an external supervised FATWA system. Eligibility requires an exact durable classification route of `FATWA`. The request lifecycle is:

```text
pending_dispatch -> awaiting_result -> approved_result
                              └──────> rejected
       │                  │
       └──────────────────┴────> cancelled
```

The bridge prepares only minimal normalized question/identity data. Failed dispatch attempts increment a counter without storing raw provider errors. Successful dispatch records only a stable bridge name and external case id.

A bridge result becomes publishable evidence only when the external result is `approved` and includes all of: non-empty answer text supplied by the supervised system, a non-empty `approved_by` value, a non-empty `source_ref`, and a stable unique external result key. A rejected result is structurally forbidden from carrying answer text or an approver.

`fatwa_bridge_results` preserves the exact approved external text; Gheras does not transform it. Duplicate identical results are idempotent, while reuse of a request/result key with different semantics fails closed.

### Publishing dispatcher

Phase 8 implements exact-source origin publishing. Publication is permitted only from one of three durable sources:

- a `resolved` FAQ resolution whose exact referenced FAQ entry is still `active` at dispatch time;
- a supervisor escalation in `responded` state with its single accepted human response;
- a FATWA bridge request in `approved_result` state with attributed external approval evidence, and only when the explicit fatwa publication policy permits an origin reply.

The dispatcher never generates, rewrites, summarizes, translates, or improves source text. The selected text is passed verbatim to the injected platform publisher.

Outbound execution is crash-safe by policy:

```text
pending -> dispatching -> succeeded
                └──────> uncertain
```

A durable `outbound_actions` intent is created before any provider call. A worker must atomically claim `pending -> dispatching` before invoking the publisher, preventing concurrent workers from both publishing the same semantic action. The deterministic idempotency key binds the event, destination platform, source kind, and exact durable evidence identity.

If a provider call succeeds, the stable external result id is stored and later duplicate dispatch requests return the same durable `succeeded` action without another provider call. If an exception occurs after the provider attempt begins, the action becomes `uncertain`; it is never automatically retried because the external side effect may already have occurred. `dispatching` and `uncertain` require explicit reconciliation rather than blind resend.

The default FATWA publication policy is `telegram_only`, so approved FATWA text is not automatically posted back to the origin comment unless a separate explicit policy configuration permits it.

### Shadow Mode boundary

Phase 9 adds an evaluation-only path over the durable evidence produced by earlier phases. `ShadowService` has no publisher or transport dependency and therefore cannot dispatch replies, supervisor messages, FATWA requests, webhooks, or provider calls.

Moderation remains authoritative in Shadow Mode. A missing moderation result is `not_ready`; `block_routing` is `blocked`; and `human_review` becomes `would_wait_human`. Semantic classification is consulted only after durable `allow_routing`.

The normalized shadow outcomes are:

- `would_publish`: exact durable content is eligible for origin publication under the current policy;
- `would_wait_human`: human supervision is required or still pending;
- `would_route_fatwa`: the event belongs to the supervised FATWA path, including approved FATWA evidence when the default `telegram_only` policy still forbids an origin reply;
- `not_ready`: required durable evidence has not yet been produced;
- `blocked`: authoritative evidence or terminal state prevents the evaluated action.

Only `would_publish` may persist `source_kind`, `evidence_id`, and `proposed_text`. SQLite enforces this invariant. The proposed text is copied exactly from an active approved FAQ entry, an accepted human supervisor response, or an externally approved FATWA result when policy permits origin publication. Other outcomes cannot carry proposed reply text.

`shadow_evaluations` is unique on `(event_id, evaluator_version)`. Duplicate and racing identical evaluations converge on one immutable row. If the same event/evaluator-version key is later recomputed with different semantics, persistence raises a conflict rather than silently rewriting historical evidence. A new evaluator version is required for a new immutable observation contract.

Shadow evaluation does not create or claim `outbound_actions`, does not transition inbound processing state, and does not call adapters. Aggregate reporting exposes only counts by platform, route, and outcome plus publishable/non-publishable totals; it does not expose proposed reply text.

### Pre-live security and readiness boundary

Phase 10 establishes the pre-live regression/readiness gate. It verifies that mock-first core behavior remains isolated from provider networks, tracks unresolved Human Gates explicitly, and refuses to classify the system as production-ready merely because functional CI is green.

Phase 11 retires the legacy scheduled/runtime path on the future active code line after the owner confirmed that the old bot is already stopped. It also adds pure provider security/readiness contracts: Meta webhook handshake/signature verification over raw bytes, Telegram webhook-secret validation, YouTube polling/quota metadata, and redaction-safe configuration readiness. Phase 11 cannot authorize live activation.

### Sandbox live-network boundary

Phase 12 introduces the first HTTP-capable provider implementations under the dedicated `app/integrations/live/` package. Network libraries and hard-coded provider endpoints are forbidden elsewhere by regression tests.

The Phase 12 clients implement the existing Phase 6 protocols for:

- Facebook Graph API comment replies;
- Instagram Graph API comment replies;
- Telegram reply and supervisor-message transport;
- YouTube comment-thread polling and comment replies.

Execution remains disabled by default. Every request requires an explicitly injected `SandboxExecutionPermit`; configuration or environment variables alone cannot create that permit, and Phase 12 defines no production permit. YouTube checks the permit before invoking its access-token provider.

The shared HTTP boundary enforces:

- HTTPS only;
- exact provider-host allowlisting (`graph.facebook.com`, `api.telegram.org`, `www.googleapis.com`);
- no URL userinfo, fragments, or non-443 ports;
- redirects rejected instead of followed;
- bounded provider-response bodies;
- redacted transport/HTTP/protocol errors that do not include provider URLs, bodies, or credential values;
- retryability limited to HTTP 429 and 5xx classification.

Meta Graph API version is explicit configuration (`META_GRAPH_API_VERSION`) and must match the constrained `vN.N` form; no silent default is embedded in routing logic. Phase 12 tests provider request contracts exclusively through `httpx.MockTransport`; CI performs no provider calls.

## Reliability rules

- Persist first, process later.
- Inbound platform events are idempotent.
- Moderation, classification, FAQ resolution, supervisor escalation, FATWA bridge state, and shadow audits are durable.
- Duplicate/racing workers converge on one semantic durable result.
- Outbound reply intents are persisted before external calls.
- Concurrent publication workers cannot both claim the same pending action.
- Provider-call uncertainty freezes the action for reconciliation instead of blind retry.
- Shadow Mode creates no external side effect or outbound publication intent.
- Shadow observations are immutable per event/evaluator version and conflicting recomputation fails closed.
- SQLite foreign keys are enabled.
- WAL mode and busy timeout are enabled where safe.
- External failure must not silently lose accepted work.
- Low-confidence or uncertain routing escalates rather than guesses.
- Possible religious content fails toward FATWA routing, never an AI-generated answer.
- FATWA text is publishable only after explicit external approval/provenance evidence.
- Secrets come from environment variables and are never committed.
- Raw external provider payloads are not blindly persisted.
- Live-network code is isolated to the governed live-integration package.
- Configuration presence never implies permission to perform an external action.

## Current implementation boundary

- Phase 0: application/configuration/CI bootstrap.
- Phase 1: durable event core, retries, state machine, inbound/outbound idempotency.
- Phase 2: mock-first fail-closed moderation and durable moderation results.
- Phase 3: mock-first routing-only classification with religious safety override.
- Phase 4: versioned approved FAQ store and exact-key durable resolution.
- Phase 5: durable human supervisor escalation/response workflow; no live Telegram calls.
- Phase 6: four-platform normalizers and injected publisher/transport protocols.
- Phase 7: durable supervised FATWA bridge request/result lifecycle.
- Phase 8: exact-source crash-safe publishing dispatcher with atomic claim and uncertainty freeze.
- Phase 9: immutable side-effect-free Shadow Mode evaluation and aggregate audit reporting.
- Phase 10: pre-live security, regression, and final-readiness gate inventory.
- Phase 11: live-integration security/readiness preparation plus owner-authorized active-code-line retirement of the legacy runtime path.
- Phase 12: sandbox-capable Meta/Telegram/YouTube HTTP clients behind an explicit non-production execution permit; provider calls remain unexecuted in CI and no production activation path exists.
