# Gheras Social Router — Phase 10 Pre-Live Readiness

## Verdict

**MOCK-FIRST V1 ARCHITECTURE / PRE-LIVE AUDIT: PASS.**

**LIVE PRODUCTION ACTIVATION: HOLD.**

The Phase 10 machine gate and adversarial review are complete. The HOLD is intentional and fail-closed. It does not indicate that the durable V1 architecture has failed. It means the repository still has unresolved production/human gates that Phase 10 is not authorized to execute automatically.

## Audited baseline

Phase 10 was branched from the Phase 9 green head:

`e3b71cf2434a406d174d0d514070fb7440de7a51`

The implementation stack through that baseline contains:

1. durable persist-first event processing and inbound/outbound idempotency;
2. moderation before classification;
3. structured routing-only classification with religious safety override;
4. versioned approved FAQ answers;
5. durable supervisor escalation and accepted human response;
6. mock-first adapters for Facebook, Instagram, Telegram, and YouTube;
7. durable supervised FATWA bridge contract;
8. exact-source crash-safe publication with atomic claim and `uncertain` freeze;
9. side-effect-free immutable Shadow Mode evaluation.

## Phase 10 validation evidence

GitHub Actions run `34456439765` on head
`a7d0f88bfdb5c2371a2d4e72a60952fdd737549c` completed successfully:

- Ruff — PASS
- Mypy — PASS
- Pytest — PASS

The same run showed the CI token restricted to `Contents: read` and `Metadata: read`.

An adversarial comparison of `phase/09-shadow-mode` to the Phase 10 audited head found that Phase 10 changes only readiness documentation and `tests/test_pre_live_security.py`; it does not alter production service/domain/persistence logic. No new-code blocker was identified. The review also verified that static boundary tests are not being represented as a substitute for dependency SCA, provider-specific live validation, or staging evidence; those remain explicit Human Gates.

## Gate status

| Gate | Status | Evidence / interpretation |
| --- | --- | --- |
| Persist-first/idempotency architecture | PASS | Durable SQLite state, unique inbound/outbound boundaries, restart/concurrency tests from earlier phases. |
| Moderation precedes semantic routing | PASS | Classification eligibility and Shadow Mode both require authoritative moderation evidence. |
| AI-generated FATWA prevention | PASS | Classifier is routing-only; FATWA answer text can originate only from an externally approved bridge result. |
| Approved FAQ only | PASS | Publication requires an exact durable FAQ resolution and the referenced entry must still be active. |
| Supervisor answer provenance | PASS | Publication requires the single durable accepted human response. |
| FATWA answer provenance | PASS | Publication requires `approved_result` plus externally supplied answer/provenance fields. |
| Publication duplicate/crash safety | PASS | Durable intent before call, atomic claim, success idempotency, and `uncertain` freeze prevent blind retry. |
| Shadow Mode side-effect isolation | PASS | No publisher/transport dependency, no outbound action creation, no processing-state mutation. |
| Four-platform domain support | PASS | Facebook, Instagram, Telegram, and YouTube normalized behind shared contracts. |
| New-code direct network boundary | PASS | Phase 10 AST/source regression tests pass and prohibit common direct network-client imports plus hardcoded HTTP endpoints in the new application boundary. |
| CI secret isolation | PASS | CI consumes no production `secrets.*`; workflow declares read-only contents permission; run evidence reports read-only contents/metadata. |
| `.env.example` secret values | PASS | Secret placeholders are present and empty and are rechecked by CI. |
| Independent adversarial review | PASS | Phase 10 diff changes only audit docs/tests; no implementation bypass or hidden waiver was identified. |
| Public tracked runtime-data hygiene | **HOLD** | Public repo still tracks `log.txt` with historical Facebook identifiers/timestamps/replies, plus legacy runtime-state/log files. |
| Legacy auto-reply cutover | **HOLD** | `.github/workflows/bot.yml` still defines a real Facebook reply workflow on a 30-minute schedule and manual dispatch. Available run history does not establish that the workflow definition is disabled. |
| Legacy religious regex path | **HOLD** | `responses.json` still includes religious keyword auto-reply logic outside the new FATWA boundary; it must not remain authoritative after cutover. |
| Live provider adapters | **HOLD** | Production OAuth/webhook/network implementations intentionally do not exist yet. |
| Supervised FATWA live connection | **HOLD** | Contract exists; real external system connection intentionally not enabled. |
| Dependency vulnerability/SCA assessment | **HOLD** | Functional dependency installation is tested; no claim of vulnerability-free resolved packages is made. |
| Staging Shadow Mode evaluation | **HOLD** | Code is ready for shadow evaluation, but representative staging/replay evidence has not yet been collected. |
| Production observability/backup/reconciliation runbook | **HOLD** | Requires deployment-specific owner decisions. |
| Merge/promotion to `main` | **HOLD / HUMAN GATE** | Stacked PRs have not been merged to `main`. |

## Repository/data-hygiene findings

### Finding DH-01 — tracked `log.txt`

Severity for live readiness: **BLOCKER / HOLD**

The repository is public and currently tracks `log.txt`. The file contains historical Facebook comment identifiers, timestamps, and reply text. `.gitignore` now lists `log.txt` and `*.log`, but ignore configuration does not remove already tracked files.

Required action: explicit owner-approved tracked-file cleanup before live promotion. Whether to rewrite historical Git objects is a separate decision because it changes published history and should not be done implicitly.

### Finding DH-02 — legacy state/log artifacts remain tracked

Severity: **HOLD / CLEANUP REQUIRED**

`seen_comments.json` and `bot_activity.log` remain tracked even though `.gitignore` excludes them. They are currently empty on the audited branch, but runtime state should not be version-controlled in the production code line.

### Finding DH-03 — secret placeholders

Status: **PASS**

`.env.example` has empty values for OpenAI, Meta, Telegram, and FATWA bridge secrets. New application settings read secrets from process environment variables and hide secret fields from dataclass representation.

No production secret value was identified in the audited `.env.example` or new `app/config.py`.

## Legacy workflow findings

### Finding WF-01 — real side-effect workflow remains defined

Severity: **BLOCKER FOR CUTOVER**

`.github/workflows/bot.yml`:

- has a `*/30 * * * *` schedule plus `workflow_dispatch`;
- loads `FB_ACCESS_TOKEN` and `FB_PAGE_ID` from GitHub secrets;
- runs root `python main.py`;
- root `bot_manager.py` performs real Graph API GET and POST calls;
- uploads `bot_activity.log` and `log.txt` as workflow artifacts.

The available repository run history has 105 runs. `Auto Reply Workflow` does not appear in the newest 100-run page. An older available run dated 2025-12-06 exists and failed. Therefore there is no evidence of a recent legacy run in the available history, but this audit does **not** assert that the workflow definition is disabled.

### Finding WF-02 — legacy dedupe is not durable across clean runners

Severity: **CUTOVER RISK**

The legacy root bot uses `seen_comments.json` as its dedupe state. The workflow checks out the repository and runs the bot but does not commit or otherwise persist the updated `seen_comments.json` back to durable shared state. GitHub-hosted runners are ephemeral. The historical `log.txt` contains repeated comment identifiers across different executions, consistent with duplicate-reply risk.

This observation is about the legacy implementation only. The new V1 uses durable database idempotency instead.

### Finding WF-03 — legacy religious keyword replies bypass new routing

Severity: **BLOCKER FOR DUAL-AUTHORITY OPERATION**

Legacy `responses.json` contains `(الله|يارب|جزاك)` mapped to a generic reply. If the legacy bot remains able to publish while Gheras V1 becomes authoritative, religious comments could bypass the new moderation/classification/FATWA design.

Required action: ensure the legacy auto-reply path is retired or otherwise unable to compete with the new router at cutover.

## Network-boundary findings

The new `app/` implementation is designed mock-first. Platform modules normalize identifiers/text and delegate future I/O through injected client protocols. Production network clients are intentionally absent.

Phase 10 regression tests fail if new core/platform-boundary Python modules directly import common live-network/vendor clients or if the new application introduces hardcoded `http://` / `https://` endpoints.

These tests are guardrails, not proof that future live integrations are secure. Provider-specific clients, OAuth/webhook logic, scopes, rate limits, retry semantics, TLS/network controls, and staging behavior remain outside the current PASS and require their own live-integration gates.

Legacy root code is intentionally excluded from the new-code PASS claim and is documented separately as a cutover HOLD.

## Dependency/configuration findings

New project metadata currently declares Python `>=3.12`, FastAPI and Uvicorn runtime ranges, and HTTPX/Mypy/Pytest/Ruff development ranges. CI runs on Python 3.12 and installs the project from these ranges.

The successful Phase 10 CI run resolved Python 3.12.14 on the hosted runner. GitHub Actions emitted a deprecation warning that `actions/checkout@v4` and `actions/setup-python@v5` target the older Node runtime and are currently being forced onto Node 24. This did not fail CI, but action-version maintenance should be included in pre-production toolchain hardening when compatible maintained releases are selected and verified.

Legacy `requirements.txt` separately contains unpinned `requests`, unpinned `python-dotenv`, and `mysql-connector-python==8.1.0`.

Phase 10 makes **no vulnerability-free claim** for either dependency set. A current software-composition analysis and a production lock/pinning decision are mandatory Human Gates before live deployment.

## Production blockers / Human Gates

The authoritative list is `docs/HUMAN_GATES.md`. The major blockers are:

- owner-approved legacy workflow cutover;
- removal/handling of tracked public runtime data;
- retirement of legacy religious regex auto-replies as an authoritative path;
- production credential/scopes provisioning outside Git;
- implementation and staging verification of live Facebook/Instagram/Telegram/YouTube adapters;
- approved live supervised-FATWA integration contract;
- dependency/SCA assessment and production lock strategy;
- representative Shadow Mode staging/replay evaluation;
- production database, backup, monitoring, reconciliation, and rollback decisions;
- explicit merge/promotion approval.

## What Phase 10 does not authorize

Phase 10 does not:

- delete tracked legacy files or rewrite Git history;
- disable `.github/workflows/bot.yml`;
- rotate/provision secrets;
- call Facebook, Instagram, Telegram, YouTube, an AI provider, or the existing FATWA bot;
- publish a reply;
- merge any phase PR to `main`;
- assert production readiness while any mandatory Human Gate remains open.

## Final Phase 10 closure

The Phase 10 audit/hardening closure conditions have been met:

1. Phase 10 security-regression tests passed Ruff/Mypy/Pytest;
2. adversarial review found no new-code blocker or hidden waiver;
3. unresolved live concerns remain explicitly recorded as HOLD/Human Gates.

Therefore **Phase 10 is PASS as a pre-live audit/hardening phase**.

**LIVE PRODUCTION ACTIVATION remains HOLD until the Human Gates are explicitly closed.**
