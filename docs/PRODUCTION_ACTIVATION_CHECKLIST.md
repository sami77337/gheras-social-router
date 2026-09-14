# Gheras Social Router — Production Activation Checklist

**Purpose:** final environment-specific gate before any live publishing is enabled.

Every unresolved item is a HOLD. Completing this checklist is not implied by engineering CI alone.

## A. Release identity

- [ ] Exact release commit SHA recorded.
- [ ] Relevant stacked PR chain has the required independent submitted review.
- [ ] Final CI for the exact release SHA is PASS.
- [ ] Point-in-time SCA is current for the exact release dependency lock.
- [ ] Production OS/architecture selected and target artifact/hash verification completed.

## B. Deployment environment

- [ ] Production OS/runtime image approved.
- [ ] Python 3.12 patch/runtime version recorded.
- [ ] Persistent SQLite volume path approved.
- [ ] Filesystem locking semantics validated for SQLite.
- [ ] Authoritative write-process topology approved.
- [ ] TLS/ingress/proxy ownership approved.
- [ ] Health/readiness collection path approved.

## C. Secrets and provider scopes

Values must remain outside Git, chat, and tickets.

- [ ] Meta access token provisioned in approved secret store.
- [ ] Meta app secret provisioned.
- [ ] Meta verify token provisioned.
- [ ] Telegram bot token/webhook secret provisioned.
- [ ] YouTube/Google credentials and required scopes provisioned.
- [ ] Moderation/classification provider credential provisioned if used.
- [ ] FATWA bridge authentication material provisioned.
- [ ] Minimum provider scopes independently reviewed.
- [ ] Rotation/revocation owner recorded.

## D. Provider sandbox validation

- [ ] Facebook ingress validation passed.
- [ ] Instagram ingress validation passed.
- [ ] Telegram ingress validation passed.
- [ ] YouTube ingress/polling validation passed.
- [ ] Webhook signature/secret failure cases verified.
- [ ] Provider rate-limit behavior verified.
- [ ] Token-expiry/authentication failure behavior verified.
- [ ] No production publishing enabled during these tests.

## E. FATWA integration

- [ ] Supervised FATWA runtime connected in staging.
- [ ] Authentication boundary verified.
- [ ] Approved-result provenance verified.
- [ ] Rejected/non-approved results cannot publish.
- [ ] Failure/restart/reconciliation behavior verified.
- [ ] Publication destination policy explicitly approved.
- [ ] Default remains `telegram_only` unless a different policy is explicitly approved.

## F. Database and recovery

- [ ] Production-equivalent database initialized successfully.
- [ ] SQLite integrity check PASS.
- [ ] Foreign-key check PASS.
- [ ] Backup destination/access policy approved.
- [ ] Verified backup created successfully.
- [ ] Backup SHA-256 recorded.
- [ ] Restore rehearsal completed in staging.
- [ ] Restore rehearsal includes post-restore reconciliation review.
- [ ] Backup retention/deletion policy approved.

## G. Monitoring and redaction

- [ ] Logs contain no secrets.
- [ ] Default logs do not contain full user comment/reply text.
- [ ] Provider error sanitization verified.
- [ ] Database-integrity alert configured.
- [ ] `uncertain` publication alert configured.
- [ ] stale `dispatching` alert threshold approved/configured.
- [ ] terminal inbound failure alert configured.
- [ ] supervisor/FATWA queue-age targets approved/configured.
- [ ] backup verification failure alert configured.
- [ ] authentication/signature failure monitoring configured.

## H. Reconciliation readiness

- [ ] Current `dispatching` count reviewed.
- [ ] Current `uncertain` count reviewed.
- [ ] Every held action has an owner.
- [ ] No held action will be blindly retried.
- [ ] Operator/provider evidence procedure rehearsed.
- [ ] `confirmed_succeeded` path rehearsed.
- [ ] `confirmed_not_sent` path rehearsed.
- [ ] reconciliation idempotency behavior verified.

## I. Staging Shadow gate

- [ ] Representative staging/replay dataset defined.
- [ ] Evaluator version recorded.
- [ ] Shadow run performed with publishing disabled.
- [ ] `would_publish` distribution reviewed.
- [ ] `would_wait_human` distribution reviewed.
- [ ] `would_route_fatwa` distribution reviewed.
- [ ] `not_ready` cases reviewed.
- [ ] `blocked` cases reviewed.
- [ ] Unexpected routing/moderation cases resolved or explicitly held.
- [ ] Shadow acceptance recorded.

## J. Cutover

- [ ] Legacy path remains retired.
- [ ] Pre-cutover verified backup completed.
- [ ] Release SHA matches reviewed/tested artifact.
- [ ] Secrets injected only through approved secret store.
- [ ] Start in non-publishing/Shadow mode.
- [ ] Readiness snapshot reviewed after startup.
- [ ] Provider ingress verified after startup.
- [ ] Supervisor/FATWA paths verified.
- [ ] Explicit owner approval to enable production publication recorded.

## K. Rollback

- [ ] Publication-disable mechanism identified and tested.
- [ ] Rollback release/artifact identified.
- [ ] Database preservation procedure tested.
- [ ] `dispatching`/`uncertain` inventory procedure tested.
- [ ] Rollback does not blindly replay held actions.
- [ ] Database restore path, if needed, is maintenance-mode only.
- [ ] Return-to-Shadow procedure tested before re-enabling publication.

## Final decision

- [ ] **LIVE ACTIVATION APPROVED**

Approval must identify the release SHA, environment, approver, timestamp, and any approved residual risks. Until that explicit record exists, live publication remains HOLD.
