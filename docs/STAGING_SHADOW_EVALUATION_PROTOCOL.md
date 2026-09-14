# Gheras Social Router — Staging Shadow Evaluation Protocol

**Status:** EVIDENCE HARNESS READY / REPRESENTATIVE EVALUATION NOT YET EXECUTED

This protocol defines how HG-09 must be executed and evidenced. It does not declare Shadow acceptance and must not be used to substitute synthetic/unit-test data for representative staging or safely replayed traffic.

## 1. Safety rules

- production publishing remains disabled throughout the Shadow gate;
- no Shadow run may bypass moderation-first routing;
- FATWA content remains externally governed; Gheras does not generate or rewrite it;
- raw user content, approved answer text, secrets, tokens, and provider payloads must not be committed to Git;
- evaluation evidence stored in Git should be aggregate/content-free unless an explicitly approved sanitized fixture is intended for repository use;
- one immutable `evaluator_version` is evaluated at a time.

## 2. Evaluation dataset identity

Before running a representative evaluation, create a private change/evidence record containing:

- dataset or replay identifier;
- source environment: sandbox, staging, or approved sanitized replay;
- collection/replay time window;
- record count presented to the router;
- platform composition;
- sanitization/redaction method when replay data is used;
- cryptographic digest of the exact evaluation corpus or manifest where operationally feasible;
- operator/reviewer responsible for the dataset;
- any intentional exclusions and their reason.

Do not put the raw corpus in this public repository when it contains user or provider data.

## 3. Evaluator identity

Record the exact:

- release/branch commit SHA;
- `evaluator_version` used by Shadow persistence;
- model/provider configuration identity when a sandbox model is used, excluding secret values;
- relevant routing/moderation policy versions;
- FAQ dataset/version or approved-store identity;
- FATWA publication policy value.

Changing semantic evaluation behavior requires a new evaluator version. Do not reuse an evaluator version for different behavior.

## 4. Execution requirements

1. confirm the environment is non-publishing;
2. verify database integrity before the run;
3. record the pre-run Shadow count for the selected evaluator version if it already exists;
4. process the approved representative dataset through the governed pre-live/staging path;
5. do not create real publication side effects;
6. preserve durable human-review/FATWA/supervisor semantics rather than forcing completion for metric convenience;
7. generate the version-scoped aggregate report with `scripts/ops_shadow_report.py`;
8. record its `evidence_sha256` and time window in the evaluation record.

If no evidence exists for the selected evaluator version, the report fails closed instead of returning a zero-count pseudo-result.

## 5. Required aggregate evidence

For the selected evaluator version, record at minimum:

- total evaluated;
- first and last persisted evaluation timestamps;
- counts by platform;
- counts by observed route (`FAQ`, `SUPERVISOR`, `FATWA`, `none` where applicable);
- counts by outcome:
  - `would_publish`;
  - `would_wait_human`;
  - `would_route_fatwa`;
  - `not_ready`;
  - `blocked`;
- report SHA-256.

The reporting service requires every platform, route, and outcome aggregate to reconcile exactly to the same evaluator-version total.

## 6. Acceptance review

No universal percentage threshold is invented in code or this protocol. Acceptance depends on the approved representative dataset, expected traffic mix, and operational policy.

The review must explicitly investigate:

- every unexpected `blocked` result;
- every unexplained `not_ready` result;
- unexpected growth in `would_wait_human`;
- any nonreligious case unexpectedly routed to FATWA;
- any religious-possible case that did not route to FATWA;
- any `would_publish` case lacking the expected approved durable source chain;
- platform-specific anomalies;
- duplicate/idempotency anomalies;
- unexpected differences from a prior accepted evaluator version, if a prior baseline exists.

Case-level review must occur through an authorized secure evidence path. Do not copy sensitive source text into a public Git issue merely to explain an aggregate.

## 7. Minimum acceptance record

The final staging Shadow evidence record must state:

- dataset/replay identifier and digest/manifest identity;
- release SHA;
- evaluator version;
- evaluation time window;
- total evaluated and aggregate report;
- aggregate evidence SHA-256;
- known exclusions;
- investigated anomalies and dispositions;
- reviewer(s);
- explicit result: `PASS`, `HOLD`, or `REJECT`;
- date/time of the decision.

`PASS` is not valid merely because CI or unit tests pass. It requires representative staging/safely replayed evidence and explicit review.

## 8. Comparison to a prior baseline

When comparing evaluator versions:

- generate one report per exact evaluator version;
- preserve each report separately;
- compare aggregate changes only after confirming the underlying evaluation datasets are identical or explicitly documenting dataset differences;
- do not attribute metric changes to code/model changes when the datasets differ without qualification.

## 9. Current gate status

Phase 19 prepares the evidence/reporting harness only. HG-09 remains HOLD until the representative staging/safely replayed evaluation described above is actually run and reviewed.
