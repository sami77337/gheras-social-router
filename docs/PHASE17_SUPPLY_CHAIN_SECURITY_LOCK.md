# Phase 17 — Supply Chain Security Lock

**Status:** ENGINEERING PASS / LIVE ACTIVATION STILL HOLD

## Scope

Phase 17 closes the non-credential software-supply-chain gate above the locked Phase 16 pre-live runtime. It does not activate any provider, provision credentials, register webhooks, or authorize production publication.

## Locked controls

- Direct runtime dependencies are exact-version pinned in `pyproject.toml`.
- Development/security dependencies are exact-version pinned.
- Build-system dependency is exact-version pinned.
- `requirements-prod.lock` contains the resolved Python 3.12 production graph.
- `requirements-build.lock` pins CI/build preparation tooling.
- `scripts/verify_prod_lock.py` rejects production lock drift and unsupported URL/editable dependency forms.
- CI runs `pip check` as a blocking consistency gate.
- CI runs `pip-audit==2.10.1` against:
  - the production lock;
  - build tooling;
  - the installed CI/development environment.
- CI reconstructs a clean production venv from `requirements-prod.lock`, runs dependency consistency checks, and compares the resolved freeze against the committed lock.
- `actions/checkout` and `actions/setup-python` are pinned to full commit SHAs.
- Checkout uses `persist-credentials: false`.
- GitHub token permissions remain `contents: read` plus metadata read supplied by GitHub.
- Regression tests prevent weakening these controls without failing CI.

## Vulnerability finding and remediation

During Phase 17, the CI/development SCA gate identified `PYSEC-2026-1845` affecting `pytest==8.4.2`.

The vulnerable version was not waived. `pytest` was upgraded to `9.1.1`, and the complete gate was rerun.

After remediation:

- production dependency audit: PASS;
- build-tool audit: PASS;
- CI/development environment audit: PASS;
- production lock reproduction: PASS;
- Ruff: PASS;
- Mypy: PASS;
- Pytest: PASS.

## Evidence

Successful remediation CI:

- run: `34603009689`
- branch: `phase/17-supply-chain-security`
- head: `727b8912f3424adbca8e85cd0ca4bd73ec086d94`

Successful supply-chain regression CI:

- run: `34603279261`
- branch: `phase/17-supply-chain-security`
- head: `50212dc04ee5b9dcebc0d12c5cc74f968fbd1627`
- all supply-chain gates, Ruff, Mypy, and Pytest passed.

The Phase 17 documentation closure commit is intentionally followed by one final CI run before the branch is considered locked.

## Point-in-time limitation

This phase records point-in-time SCA evidence. It does not claim that the dependency graph will remain vulnerability-free. SCA must run again whenever dependency declarations or lock files change and before a production release.

## Deferred target-specific integrity

Wheel/hash locking is intentionally deferred until the production OS and architecture are selected. Hashing a package set for an assumed platform would be false reproducibility evidence.

Once the deployment target is fixed, release preparation should generate and verify target-compatible artifacts/hashes without changing the application safety model.

## Remaining Human Gates

Phase 17 does not close:

- real provider credentials/scopes and sandbox validation;
- supervised FATWA live integration;
- staging Shadow evaluation;
- production environment, backup, monitoring, ingress, reconciliation, and rollback decisions;
- independent review of the stacked implementation chain;
- promotion/merge to `main`;
- production activation.

No secret, production credential, live provider call, webhook registration, OAuth exchange, AI-generated FATWA, or production publication is introduced by this phase.
