# Phase 18 — Production Operations & Recovery Lock

**Status:** ENGINEERING PREPARATION PASS / LIVE ACTIVATION HOLD

## Scope

Phase 18 closes the non-live operational preparation layer above the locked Phase 17 supply-chain gate. It prepares local operational visibility, verified SQLite backup/integrity handling, durable publication reconciliation, and production runbooks without deploying Gheras or performing any provider-side action.

## Locked engineering controls

### Read-only readiness

- `SQLiteDatabase.connect_readonly()` refuses a missing database and does not create it.
- `OperationalReadinessService` selects counts/state only.
- Readiness does not select inbound comment text, approved reply text, credentials, idempotency keys, or provider result identifiers.
- Operator attention is raised for database-integrity failure, foreign-key violations, held publication states, or terminal inbound failures.

### Verified SQLite backup

- backup uses SQLite's backup API rather than copying a live WAL database file;
- a missing source is refused;
- an existing destination is refused rather than overwritten;
- the new backup must pass SQLite integrity and foreign-key checks;
- a newly created invalid backup is removed on failure;
- successful backup evidence includes size, timestamp, and SHA-256.

### Publication reconciliation

- `dispatching` and `uncertain` actions remain fail-closed until provider-side outcome is verified;
- reconciliation evidence is stored durably in `publication_reconciliations`;
- each reconciliation records prior status, operator reference, evidence reference, external reconciliation key, decision, and provider result ID when success is confirmed;
- external reconciliation keys are idempotent and conflicting semantics are rejected;
- reconciliation and outbound-action state transition occur in one `BEGIN IMMEDIATE` transaction;
- `confirmed_succeeded` moves the action to `succeeded` with a stable provider result ID;
- `confirmed_not_sent` moves the action to `pending` but does not call a publisher;
- unresolved provider outcome remains held; no inference and no blind retry are authorized.

### Operational tools and procedures

- `scripts/ops_readiness.py` prints content-free readiness JSON;
- `scripts/ops_backup.py` creates one verified, non-overwriting backup;
- `scripts/ops_reconcile_publication.py` requires explicit provider-outcome verification before recording a reconciliation decision;
- `docs/PRODUCTION_OPERATIONS_RUNBOOK.md` defines backup/restore, redaction, monitoring, reconciliation, ingress, Shadow, cutover, rollback, and incident procedures;
- `docs/PRODUCTION_ACTIVATION_CHECKLIST.md` keeps every environment-specific or external dependency as an explicit HOLD until verified.

## Validation evidence

Pre-lock full CI after implementation and lint remediation:

- run: `34607277283`
- branch: `phase/18-production-operations`
- head: `269e8744f9a9af64dd43e6a49e83f3271e267a00`
- production lock metadata: PASS
- dependency consistency: PASS
- production dependency audit: PASS
- build-tool audit: PASS
- CI/development audit: PASS
- production environment reproduction: PASS
- Ruff: PASS
- Mypy: PASS
- Pytest: PASS

The documentation closure commits are followed by one final CI run before the branch is treated as locked.

## Adversarial review result

The Phase 17 → Phase 18 diff was inspected for scope expansion. The changes are limited to local SQLite operations, durable reconciliation, tests, local scripts, and operational documentation. No provider network client is invoked by the new operational layer, no credential is introduced, and no live publishing path is enabled.

The reconciliation design deliberately separates provider-side verification from later publishing: a `confirmed_not_sent` decision only restores `pending` state. Any subsequent publication still requires the separate governed dispatcher.

## Human Gates that remain

Phase 18 does not select or validate the real production environment. The following remain HOLD:

- production OS/architecture and target artifact/hash verification;
- process topology and persistent SQLite filesystem/volume;
- secret store, credentials, provider scopes, and rotation ownership;
- real Facebook/Instagram/Telegram/YouTube sandbox validation;
- supervised FATWA live integration and final publication policy decision;
- production-equivalent backup/restore rehearsal;
- monitoring destinations, service targets, and alert thresholds;
- TLS/public ingress and network controls;
- representative staging Shadow evaluation and acceptance;
- independent submitted review of the stacked implementation chain;
- reviewed promotion to `main`;
- explicit production publication activation.

No secret, credential, external provider call, webhook registration, OAuth exchange, deployment, AI-generated FATWA, or production publication is introduced by Phase 18.
