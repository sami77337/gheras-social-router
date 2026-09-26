# Gheras Social Router — Human Gates Before Live Activation

This is the current authoritative gate summary after V1 engineering through Phase 22 was promoted to `main` on 2026-09-26. Historical phase lock/readiness documents remain point-in-time evidence and are not rewritten to look current.

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

The recorded pytest advisory was remediated by upgrading to `pytest==9.1.1`, after which audits passed. Phase 20–22 promotion retained the same blocking supply-chain gates. Final post-merge `main` CI run `36228719988` again passed the production lock, dependency consistency, production/build/development audits, production-environment reproduction, Ruff, Mypy, and Pytest gates.

This is not a permanent vulnerability-free guarantee. SCA must be rerun when dependencies change and before production release. Wheel/hash locking remains dependent on the selected production OS/architecture.

## HG-09 — Representative Shadow evaluation

**Status: ENGINEERING STACK PASS THROUGH PHASE 22 / REPRESENTATIVE ACCEPTANCE HOLD**

The engineering path is now present on `main`:

- Phase 19: evaluator-version-scoped, content-free Shadow evidence harness with aggregate reconciliation and deterministic SHA-256 evidence;
- Phase 20: strict private representative replay loader/runner with exact corpus digest, bounded input, evaluator isolation, idempotent ingestion, and zero-publication checks;
- Phase 21: read-only historical acquisition for Facebook, Instagram, Telegram, and YouTube, including offline Telegram export import, bounded provider reads, normalized replay output, author-identity omission, and fail-closed semantic-conflict handling;
- Phase 22: representative Shadow execution orchestration with validated private FAQ snapshot support, environment-only model credential handling, explicit private-content processing acknowledgement, decision ceilings, release/model/evaluator/corpus evidence binding, and content-free atomic evidence output.

CI and engineering readiness do not constitute representative acceptance. No real external-model representative run was executed as part of the Phase 20–22 promotion.

HG-09 remains HOLD until an approved representative sandbox/staging or safely replayed private corpus is executed under the applicable private-content/provider Human Gate, publication remains disabled, anomaly cases are reviewed through an authorized secure path, and an explicit `PASS`, `HOLD`, or `REJECT` acceptance decision is recorded.

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

**Status: PASS THROUGH PHASE 22 — OWNER-AUTHORIZED REVIEW WAIVERS RECORDED**

The Phase 19 integrated promotion remains recorded under PR #44 and its owner-authorized waiver.

The later Phase 20–22 stacked continuation was promoted on 2026-09-26 under a separate owner-authorized waiver recorded in Issue #52. The assistant adversarial review was PASS but was **not independent** and must not be represented as independent acceptance.

Promotion order and post-merge evidence:

- PR #47 / Phase 20 → merge commit `9eb4a26b927ea4a66dbb5007612f92bc662dc6f8`; post-merge CI `36228501965` — PASS;
- PR #49 / Phase 21 → merge commit `2f0a94ae54dbcdc5c61481534c22f345da0e476f`; post-merge CI `36228622887` — PASS;
- PR #51 / Phase 22 → merge commit `8dc51ad35a96cda40a3374010bbf2953d16389ba`; post-merge CI `36228719988` — PASS.

All three post-merge runs passed production lock verification, dependency consistency, production/build/development audits, production-environment reproduction, Ruff, Mypy, and Pytest.

These promotion waivers apply only to the recorded code promotions. They do not waive any external/private-content, credential, provider, deployment, publication, or production-live Human Gate.

## HG-12 — Production publication activation

**Status: HOLD — EXPLICIT LIVE ACTIVATION REQUIRED**

Promotion to `main` is not production activation. No live provider registration, OAuth exchange, deployment, webhook activation, production polling, or production reply publication is authorized solely by the merge.

Production publication may be enabled only after the applicable HG-04 through HG-10 external/environment gates have sufficient evidence and the owner explicitly authorizes live activation.