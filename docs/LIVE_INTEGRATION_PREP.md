# Gheras Social Router — Live Integration Preparation

Provider-contract snapshot date: **2026-09-10**.

This document is a preparation/runbook artifact. It does not authorize external calls or contain credential values.

## Safety state

- Legacy scheduled Facebook workflow: removed from the Phase 11 active branch.
- Legacy root entry point: retired and fail-closed.
- Tracked runtime log/state files: removed from the Phase 11 active branch.
- Git history: unchanged.
- Live network clients: not enabled.
- Production publishing: not enabled.
- Maximum code readiness state in this phase: `ready_for_sandbox_validation`.

## Configuration matrix

| Target | Identity / non-secret configuration | Secret-bearing configuration | Prepared verification/ingestion rule |
| --- | --- | --- | --- |
| Facebook | `META_PAGE_ID` | `META_ACCESS_TOKEN`, `META_APP_SECRET`, `META_VERIFY_TOKEN` | Meta GET challenge + HMAC-SHA256 raw-body verification |
| Instagram | `INSTAGRAM_BUSINESS_ACCOUNT_ID` | `META_ACCESS_TOKEN`, `META_APP_SECRET`, `META_VERIFY_TOKEN` | Shared Meta webhook security boundary |
| Telegram | `TELEGRAM_SUPERVISOR_CHAT_ID` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | exact webhook secret header comparison; configured token shape validated |
| YouTube | `YOUTUBE_CLIENT_ID`, `YOUTUBE_CHANNEL_ID` | `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | comment ingestion prepared as `commentThreads.list` polling |
| AI provider | none in Phase 11 | `OPENAI_API_KEY` | configuration only; no model API call in Phase 11 |
| FATWA bridge | none in Phase 11 | `FATWA_BRIDGE_SECRET` | configuration only; supervised bridge remains disconnected |

## Meta webhook preparation

The prepared helper:

1. requires `hub.mode == subscribe`;
2. compares the received verify token to the configured token using constant-time comparison;
3. echoes the challenge verbatim only after successful verification;
4. validates event notifications with HMAC-SHA256 over the original raw request bytes before JSON parsing;
5. rejects malformed, wrong-length, non-hex, and mismatched signatures.

No callback URL or Graph API endpoint is hardcoded in the application.

## Telegram webhook preparation

The prepared helper:

1. validates the configured webhook secret as 1–256 characters;
2. permits only letters, digits, underscore, and hyphen;
3. compares the inbound secret header using constant-time comparison;
4. fails closed on missing or mismatched evidence.

Webhook registration itself is intentionally not performed.

## YouTube preparation

The application does not invent a comment webhook. The current preparation contract uses comment-thread polling.

Current documentation snapshot recorded for capacity planning:

- `commentThreads.list`: 1 quota unit per call;
- maximum documented `maxResults`: 100;
- `comments.insert` reply: 50 quota units per call.

These are provider metadata, not permanent product constants. They must be rechecked before production activation.

## Readiness reporting

`IntegrationReadinessService` returns only:

- integration target;
- readiness state;
- names of missing variables;
- names of invalid variables;
- `live_activation_allowed=False`.

It never returns or renders secret values.

## Next gate after Phase 11

After CI and review pass, the next engineering lane may implement sandbox-capable provider network clients behind a separate live-integration boundary. That lane must remain disabled by default and must not be exercised until credentials are provisioned outside Git.
