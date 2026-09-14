# Phase 11 — Live Integration Preparation & Legacy Cutover Cleanup

## Objective

Prepare the audited V1 architecture for provider-specific sandbox/staging integration without enabling any live external side effect.

## Governing constraints

- Owner confirms the legacy Facebook bot is stopped.
- Retire the legacy executable/workflow path from the active code line without rewriting Git history.
- Remove tracked runtime logs/state from the active code line.
- No real token, secret, OAuth grant, webhook registration, external API call, or reply publication.
- Keep Facebook, Instagram, Telegram, and YouTube behind injected client/transport boundaries.
- Keep moderation before classification.
- AI never generates or delivers a FATWA.
- FAQ publication can use approved active entries only.
- Human/FATWA answers retain durable provenance.
- Outbound ambiguous failures remain fail-closed/uncertain; no blind retry.
- No merge to main in this phase.

## Provider preparation snapshot — 2026-09-10

### Meta / Facebook / Instagram

- Webhook verification handshake uses `hub.mode`, `hub.verify_token`, and `hub.challenge`.
- Event-notification verification must operate on the raw request body before JSON parsing.
- Phase 11 implements cryptographic verification as a pure standard-library helper; no network client is introduced.

### Telegram

- `setWebhook` supports a configured `secret_token`.
- Telegram sends the configured value in `X-Telegram-Bot-Api-Secret-Token` on webhook requests.
- Phase 11 validates configured-token shape and performs constant-time comparison; it does not register a webhook.

### YouTube

- Comment ingestion is prepared as polling of `commentThreads.list`, not an invented comment webhook.
- Current documented quota snapshot: comment-thread listing = 1 unit per call; replying with `comments.insert` = 50 units per call.
- These values are readiness metadata and must be re-verified before production activation.

## Deliverables

1. Fail-closed retired legacy entry point.
2. Legacy workflow and tracked runtime artifacts removed from the active branch.
3. Pure webhook/auth verification helpers for Meta and Telegram.
4. YouTube polling/quota contract.
5. Environment-only configuration placeholders for provider identities and secrets.
6. Redaction-safe readiness service that reports only missing variable names, never secret values.
7. Tests for valid/invalid signatures, webhook secrets, configuration readiness, YouTube policy bounds, and accidental live-network regression.
8. Documentation update and final CI/review gate.

## Exit criteria

- Ruff PASS.
- Mypy PASS.
- Pytest PASS.
- No live-network/vendor SDK dependency imported by the new core/platform boundary.
- No hardcoded provider HTTP endpoint inside `app/`.
- No production secret committed.
- Legacy scheduled auto-reply workflow absent from this branch.
- Runtime logs/state absent from this branch.
- Live credential provisioning, webhook registration, sandbox calls, and production publication remain explicit HOLD gates.