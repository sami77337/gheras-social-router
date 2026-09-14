# Phase 15 — Structured AI Decision Adapters

Status: IMPLEMENTATION PASS / LIVE PROVIDER HOLD

## Scope completed

Phase 15 adds a provider-neutral `StructuredDecisionClient` boundary plus strict moderation and classification adapters. No concrete model-provider SDK, HTTP client, credential, or production activation is included.

The adapters expose only routing evidence:

- moderation: verdict, severity, confidence, categories, text_assessed, media_assessed;
- classification: proposed_route, confidence, religious_possible, faq_key.

There is no output field for an answer, reply, explanation, or fatwa text.

## Fail-closed schema boundary

Provider-decoded output is rejected before domain assessment creation when it is not the exact allowed object shape. Rejection covers extra or missing keys, unsupported enums, invalid booleans, malformed FAQ keys, duplicate moderation categories, non-finite confidence, out-of-range confidence, and non-object values.

User text and media metadata remain separate untrusted data fields in `StructuredDecisionRequest`; they are not interpolated into the fixed adapter instructions.

The fixed instructions explicitly prohibit answering the user and prohibit generating, summarizing, translating, or rewriting a fatwa.

## Service-level behavior

Existing durable service policies remain authoritative after the adapter boundary:

- rejected or failed moderation evidence becomes human review;
- rejected or failed classification evidence becomes SUPERVISOR routing;
- low-confidence FAQ evidence becomes SUPERVISOR routing;
- `religious_possible=true` reaches the existing religious-safety override and routes to FATWA;
- no adapter exception text or raw model output is persisted by these services.

## Adversarial review

The Phase 15 diff was reviewed against these failure modes:

1. model-generated answer smuggled as an extra field — rejected;
2. model-generated fatwa text smuggled as an extra field — rejected;
3. prompt-injection text attempting to rewrite adapter instructions — remains user data;
4. boolean used as numeric confidence — rejected;
5. NaN/infinity/out-of-range confidence — rejected;
6. duplicate or unknown moderation categories — rejected;
7. FAQ key attached to a non-FAQ proposed route — rejected;
8. malformed model output reaching durable FAQ publication — blocked by fail-closed service routing;
9. religious content incorrectly left on FAQ route — overridden to FATWA by existing policy.

No in-project blocker was found. This is not an independent review and does not satisfy the repository's independent-review promotion gate.

## CI evidence

GitHub Actions run `34534170091` on head `2a9b14976b3044d3b455ac913df6afd6df19233e`:

- Ruff: PASS
- Mypy: PASS
- Pytest: PASS

## Remaining live Human Gate

A concrete model provider is intentionally not selected or connected in this phase. Live activation requires an explicit provider/configuration decision, provider-specific security review, real credentials supplied through an approved secret channel, and staging validation. No token or secret should be pasted into source code, issues, pull requests, or chat.
