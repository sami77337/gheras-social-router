# Phase 14 — End-to-End Sandbox Assembly & Replay Validation

## Verdict

**PASS — non-production replay/runtime boundary.**

Production activation remains outside this phase.

## What was composed

`SandboxReplayRuntime` wires the existing durable V1 components over one SQLite database:

1. exact/idempotent inbound ingestion;
2. moderation and local moderation policy;
3. classification only after `ALLOW_ROUTING`;
4. approved FAQ resolution;
5. human-supervisor evidence;
6. supervised FATWA bridge evidence;
7. side-effect-free Shadow evaluation;
8. durable publishing with recording-only fake publishers.

No live provider client is injected into this runtime.

## Replay integrity

The runtime compares replay evidence to already durable moderation/classification evidence. A replay that changes previously durable semantics raises `ReplayEvidenceConflict` instead of silently adopting new evidence.

FAQ seed evidence is also stable: an existing active FAQ must match answer text, source reference, approver, and approval time exactly or replay fails closed.

Wrong-route downstream evidence is rejected. Non-`ALLOW_ROUTING` moderation cannot be supplemented with FAQ, supervisor, or FATWA evidence.

## External-side-effect containment

The sandbox publisher stores only:

- platform;
- target identity used by the local replay;
- SHA-256 of the candidate reply text;
- text length.

It does not retain the reply text and performs no HTTP/network operation. The replay report itself contains only platform/route/outcome counts and booleans/enums; it contains no user message or reply text.

## FATWA invariant

The default `FatwaPublicationPolicy.TELEGRAM_ONLY` remains authoritative. Even an approved external FATWA result is not dispatched to the originating comment under the default policy. A dedicated sandbox test may instantiate `ORIGIN_ONLY` only to verify that, when explicitly allowed in the sandbox, the exact externally approved answer fingerprint is used; no answer is generated or rewritten by Gheras.

## Restart and idempotency proof

The suite reopens `SandboxReplayRuntime` on the same SQLite file and replays the same scenario. The durable inbound event and succeeded outbound action are reused and the fresh recording publisher is not called. Same-process duplicate replay likewise creates neither a second event nor a second outbound action/provider call.

## Four-platform matrix

The end-to-end FAQ matrix executes Facebook, Instagram, Telegram, and YouTube scenarios. Each reaches publication only through active approved FAQ evidence and records the SHA-256 fingerprint of the exact approved answer.

Additional scenarios verify:

- supervisor route with accepted human response;
- supervisor route without human response remains waiting;
- low-confidence FAQ routes to supervisor;
- moderation human-review prevents classification and outbound work;
- approved FATWA remains origin-blocked by default;
- durable moderation/classification drift fails closed;
- changed FAQ approval fails closed;
- wrong-route evidence fails closed;
- replay report remains content-free.

## Validation

Implementation head before this documentation commit: `b124f290f37ff2ee8536a8e0e2635b65b104e04e`.

GitHub Actions run `34482420462`:

- Ruff: PASS
- Mypy: PASS
- Pytest: PASS

## Adversarial review

In-project adversarial review: **PASS** for the sandbox boundary.

Review focus:

- no live-network/provider dependency in `app/sandbox/replay.py`;
- persist-first ordering is retained;
- moderation gate precedes classification;
- religious-possible classification still reaches FATWA;
- FAQ/supervisor/FATWA text sources remain exact durable evidence;
- Shadow/publishing disagreement fails closed;
- duplicate and restart replays do not duplicate publication;
- report data does not contain raw user/reply text.

This review is not an independent external review. Independent review remains required before promotion to `main`.

## External gate still excluded

No production credential, OAuth grant, webhook registration, live provider call, live moderation/classification model call, or real publication was performed in Phase 14.
