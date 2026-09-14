# Gheras Social Router — Human Gates Before Live Activation

This is the current authoritative gate summary after the V1 engineering stack through Phase 19 was promoted to `main` on 2026-09-14. Historical phase lock/readiness documents remain point-in-time evidence and are not rewritten to look current.

## HG-01 — Legacy Facebook bot cutover

**Status: PASS FOR ACTIVE CODE LINE / OWNER-ASSERTED RUNTIME STOP**

The repository owner stated on 2026-09-10 that the legacy bot was already stopped. The promoted code line removes `.github/workflows/bot.yml`, replaces root `main.py` with a fail-closed retired stub, and does not import the legacy runtime from the new application.

This records the owner's runtime assertion accurately; it does not claim independent verification of the historical production process.

## HG-02 — Public tracked runtime-data cleanup

**Status: PASS FOR ACTIVE CODE LINE / HISTORY REWRITE NOT PERFORMED**

`log.txt`, `seen_comments.json`, and `bot_activity.log` are removed from the active code line and remain ignored. Historical Git objects were intentionally not rewritten.

## HG-03 — Legacy religious-response retirement

**Status: PASS FOR AUTHORITATIVE CODE PATH**

The old response path is not authoritative on `main`. Religious routing is governed by moderation/classification/FATWA invariants in the new application.

## HG-04 — Real credentials and provider scopes

**Status: HOLD — EXTERNAL CREDENTIALS REQUIRED**

Production/sandbox credentials and scopes have not been provisioned or verified for Meta, Telegram, YouTube, the selected structured-decision provider, or the supervised FATWA integration.

Secrets must remain outside Git and must not be pasted into chat. Use an approved secret store when the deployment target is selected.

## HG-05 — Real provider sandbox validation

**Status: ENGINEERING PASS / REAL EXECUTION HOLD**

Sandbox-capable clients and authenticated ingress contracts exist for Facebook, Instagram, Telegram, and YouTube behind `app/integrations/live/` and explicit `SandboxExecutionPermit` checks. The default FastAPI app does not mount provider ingress automatically.

CI uses mocks and does not establish provider-side permissions, OAuth behavior, webhook registration, token refresh, quotas/rate limits, or real network behavior. Those require controlled external validation.

## HG-06 — Supervised FATWA-system integration

**Status: ENGINEERING CONTRACT PASS / LIVE CONNECTION HOLD**

The durable FATWA bridge accepts only externally supplied, attributable approved-result evidence. Gheras does not generate, summarize, translate, or rewrite a fatwa.

The real supervised FATWA system still requires authenticated sandbox/staging integration, provenance verification, failure handling, and reconciliation evidence.

## HG-07 — FATWA publication policy

**Status: SAFE DEFAULT ACTIVE**

The default remains `telegram_only`, so an approved FATWA result is not automatically posted back to the origin comment. Changing to `origin_only` or `both` is a later production policy decision and is not implied by promotion to `main`.

## HG-08 — Dependency and supply-chain security

**Status: ENGINEERING PASS / POINT-IN-TIME EVIDENCE**

Phase 17 established exact direct pins, production/build lock files, `pip check`, `pip-audit` gates for runtime/build/dev, clean production-environment reproduction, full-SHA GitHub Action pinning, and `persist-credentials: false`.

The recorded pytest advisory was remediated by upgrading to `pytest==9.1.1`, after which audits passed. Post-merge `main` CI run `34836900921` again passed the supply-chain gates.

This is not a permanent vulnerability-free guarantee. SCA must be rerun when dependencies change and before production release. Wheel/hash locking remains dependent on the selected production OS/architecture.

## HG-09 — Representative Shadow evaluation

**Status: HARNESS PASS / REPRESENTATIVE EVALUATION HOLD**

Phase 19 provides an evaluator-version-scoped, content-free evidence harness with aggregate reconciliation and deterministic SHA-256 evidence. Missing evidence fails closed.

HG-09 itself remains HOLD until a representative sandbox/staging or safely replayed dataset is identified, executed with publication disabled, reviewed for anomalies, and given an explicit `PASS`, `HOLD`, or `REJECT` acceptance decision.

## HG-10 — Production environment and operations

**Status: ENGINEERING PREPARATION PASS / ENVIRONMENT-SPECIFIC HOLD**

Phase 18 provides read-only operational readiness, verified SQLite backup, integrity/foreign-key checks, durable publication reconciliation, and production runbook/checklist material.

The following still require the actual deployment environment and owner/operator decisions:

- production OS/architecture and process/runtime topology;
- persistent SQLite storage/filesystem;
- approved secret store and rotation ownership;
- backup retention/access policy and a production-equivalent restore rehearsal;
- monitoring destination, service targets, and alert thresholds;
- TLS termination, public ingress, firewall/network controls;
- provider credentials/scopes and real sandbox validation;
- supervised FATWA integration;
- representative Shadow acceptance.

## HG-11 — Promotion to `main`

**Status: PASS — OWNER-AUTHORIZED REVIEW WAIVER RECORDED**

PR #44 (`phase/19-shadow-evidence-harness` → `main`) was merged on 2026-09-14 as merge commit:

`83a4d64ba5208ea2389aa33f029763676712c5fd`

Evidence:

- locked Phase 19 head `e97537a7e6cafbe47cf0c817de41020c0e79e8e8`;
- Phase 19 branch CI `34608463775` — PASS;
- integrated PR-to-main CI `34610230607` — PASS;
- assistant adversarial review found no merge-blocking defect;
- repository owner explicitly authorized treating that assistant review as sufficient and merging.

The previous requirement for a genuinely independent submitted review was **explicitly waived by the owner for this promotion only**. The assistant review must not be represented as an independent review.

Post-merge `main` CI run `34836900921` completed successfully across production lock verification, dependency consistency, production/build/development SCA, production-environment reproduction, Ruff, Mypy, and Pytest.

## HG-12 — Production publication activation

**Status: HOLD — EXPLICIT LIVE ACTIVATION REQUIRED**

Promotion to `main` is not production activation. No live provider registration, OAuth exchange, deployment, webhook activation, production polling, or production reply publication is authorized solely by the merge.

Production publication may be enabled only after the applicable HG-04 through HG-10 external/environment gates have sufficient evidence and the owner explicitly authorizes live activation.