# Gheras Social Router — Human Gates Before Live Activation

This document tracks only actions that still require external credentials, live provider validation, irreversible repository operations, or production activation decisions. Routine non-live engineering proceeds without waiting for additional approval.

## HG-01 — Legacy Facebook bot cutover

**Status:** OWNER-CONFIRMED STOPPED / ACTIVE-CODE-LINE RETIREMENT COMPLETE IN PHASE 11

On 2026-09-10 the repository owner explicitly confirmed that the legacy bot is already stopped and authorized proceeding without further routine approval waits.

Phase 11 therefore makes the future active code line fail-closed:

- `.github/workflows/bot.yml` is removed from the Phase 11 branch;
- root `main.py` is replaced by a retired fail-closed stub;
- the historical implementation remains recoverable from Git history.

No claim is made that Phase 11 changed the already-existing production runtime state. The owner supplied that runtime-state assertion; the code-line changes prevent accidental reactivation after promotion.

## HG-02 — Public tracked runtime-data cleanup

**Status:** ACTIVE-CODE-LINE CLEANUP COMPLETE / HISTORY REWRITE NOT PERFORMED

Phase 11 removes the following tracked runtime artifacts from the active branch:

- `log.txt`;
- `seen_comments.json`;
- `bot_activity.log`.

`.gitignore` continues to exclude these files.

Historical Git objects are intentionally not rewritten. Rewriting public repository history is a separate high-impact/irreversible operation and is not required to continue engineering or sandbox validation.

## HG-03 — Legacy religious-response retirement

**Status:** AUTHORITATIVE RUNTIME PATH RETIRED IN PHASE 11

The historical `responses.json` remains repository evidence, but the old entry point is fail-closed and its scheduled workflow is removed on the Phase 11 branch. The new application does not import the legacy regex response logic.

After promotion, the legacy rules must remain non-authoritative; religious routing continues exclusively through the governed moderation/classification/FATWA path.

## HG-04 — Live platform credentials and scopes

**Status:** NOT PROVISIONED / NOT VERIFIED

No production credentials are committed. `.env.example` contains empty placeholders only.

Before sandbox/live provider validation, provision the minimum required credentials/scopes outside Git for:

- Facebook / Instagram;
- Telegram;
- YouTube;
- the selected moderation/classification provider, if used;
- the supervised FATWA bridge.

Credential values must never be posted in chat or committed to the repository.

## HG-05 — Live platform adapter implementation

**Status:** SANDBOX-CAPABLE CLIENTS IMPLEMENTED / REAL PROVIDER EXECUTION NOT YET VALIDATED

Phase 11 adds provider-specific webhook/readiness security contracts. Phase 12 adds HTTP-capable provider clients for Facebook, Instagram, Telegram, and YouTube behind the dedicated `app/integrations/live/` boundary.

These clients are still fail-closed for real execution:

- every request requires an explicitly injected `SandboxExecutionPermit`;
- configuration values cannot create that permit;
- there is no production execution permit in Phase 12;
- CI uses `httpx.MockTransport` only and performs no provider calls;
- OAuth/token exchange, webhook registration, real polling, and provider-side permission/scope validation have not been executed.

Real sandbox credentials and provider-side validation remain a Human Gate because they require external accounts/secrets and real network side effects.

## HG-06 — Supervised FATWA-system integration

**Status:** NOT CONNECTED BY DESIGN

The Phase 7 bridge remains a durable contract. No external FATWA runtime is called by Phases 11–19.

The real connection requires authentication material, approved-result provenance verification, and failure/reconciliation validation in sandbox/staging before activation.

## HG-07 — FATWA publication policy

**Status:** SAFE DEFAULT ACTIVE IN CODE

The default remains `telegram_only`. An approved FATWA result is therefore not automatically posted back to the origin comment.

Any later move to `origin_only` or `both` remains a production policy decision after supervised FATWA integration validation.

## HG-08 — Dependency/security assessment

**Status:** ENGINEERING PASS / POINT-IN-TIME SCA COMPLETE IN PHASE 17

Phase 17 implements and records the non-credential supply-chain gate:

- direct project, development, security, and build dependencies are exact-version pinned;
- `requirements-prod.lock` records the resolved Python 3.12 production dependency graph;
- `requirements-build.lock` pins `pip` and `setuptools` used by CI/build preparation;
- `pip check` is a blocking CI gate;
- `pip-audit==2.10.1` audits the production lock, build tooling, and CI/development environment;
- CI reconstructs a clean production environment from the lock and compares its resolved freeze against the committed lock;
- GitHub Actions are pinned to full commit SHAs and checkout uses `persist-credentials: false`;
- regression tests prevent removal of the SCA gates, reintroduction of broad direct dependency ranges, or weakening of the Action pinning rules.

The audit initially found `PYSEC-2026-1845` in `pytest==8.4.2`. Phase 17 upgraded pytest to `9.1.1`; subsequent runtime, build-tool, and CI/development audits all passed.

This is point-in-time evidence only and is not a permanent vulnerability-free guarantee. Re-run SCA when dependencies or lock files change and before production release.

A wheel/hash lock is intentionally deferred until the production OS/architecture is selected. Generating wheel hashes for an unchosen target would create false reproducibility evidence rather than strengthen the gate.

## HG-09 — Staging Shadow Mode evaluation

**Status:** EVIDENCE HARNESS READY IN PHASE 19 / REPRESENTATIVE EVALUATION HOLD

Phase 19 prepares the evidence and review layer without claiming the staging gate has passed:

- Shadow evidence reporting is read-only and content-free;
- one exact `evaluator_version` must be selected explicitly;
- missing evaluator-version evidence fails closed rather than producing a zero-count pseudo-result;
- counts are reported by platform, observed route, and Shadow outcome;
- all aggregate dimensions must reconcile to the same selected evaluator-version total;
- the report records the first/last persisted timestamps and a deterministic SHA-256 over the aggregate evidence;
- `scripts/ops_shadow_report.py` emits the machine-readable report without selecting proposed reply text or inbound user content;
- `docs/STAGING_SHADOW_EVALUATION_PROTOCOL.md` defines dataset identity, evaluator identity, safe execution, aggregate evidence, anomaly review, comparison rules, and the minimum acceptance record;
- no universal acceptance percentage is invented by code.

The actual HG-09 PASS still requires representative sandbox/staging or safely replayed data, an identified dataset/corpus, execution through the governed Shadow path with publishing disabled, anomaly review, and an explicit `PASS`, `HOLD`, or `REJECT` decision. Synthetic/unit tests do not satisfy this gate.

No production reply publishing is authorized during this gate.

## HG-10 — Production configuration and operations

**Status:** ENGINEERING PREPARATION PASS IN PHASE 18 / ENVIRONMENT-SPECIFIC ACTIVATION HOLD

Phase 18 completes the non-live operational preparation layer:

- a provider-neutral production operations/runbook and explicit activation checklist are defined;
- read-only operational readiness reports counts/state only and does not select comment/reply text or secrets;
- SQLite integrity and foreign-key checks are available without creating or mutating a missing database;
- verified SQLite-native backup refuses implicit overwrite, verifies the new backup, and emits SHA-256 evidence;
- publication `dispatching`/`uncertain` holds are visible through a content-free reconciliation inventory;
- publication reconciliation is durable, idempotent, and atomic: provider-confirmed success closes an action as `succeeded`, while provider-confirmed non-delivery returns it to `pending` without publishing anything;
- reconciliation requires explicit operator/evidence references and never performs a blind retry;
- logging/redaction, monitoring classes, backup/restore, cutover, rollback, and incident priorities are documented;
- local operational CLIs are provided for readiness, verified backup, and guarded reconciliation without provider calls.

The following remain Human Gates because they depend on the actual deployment environment or external systems:

- production OS/architecture and runtime/process topology;
- persistent SQLite volume/filesystem selection and validation;
- approved secret store and credential rotation ownership;
- backup retention/access policy and a production-equivalent restore rehearsal;
- monitoring destination, service targets, and alert thresholds;
- TLS termination, public ingress, and network controls;
- real provider sandbox validation and scopes;
- supervised FATWA live integration;
- staging Shadow acceptance;
- explicit production publication activation.

Production activation remains blocked until those environment-specific choices and rehearsals are completed. Phase 18 does not deploy or modify any live provider configuration.

## HG-11 — Merge/promotion to `main`

**Status:** REVIEW/CI GATE REQUIRED

Implementation remains on stacked phase branches/PRs. Routine engineering does not wait for additional owner messages, but promotion to `main` must still preserve the project rule: relevant CI and independent review gates must pass before merge.
