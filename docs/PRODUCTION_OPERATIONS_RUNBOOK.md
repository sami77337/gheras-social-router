# Gheras Social Router — Production Operations Runbook

**Mode:** PRE-LIVE PREPARATION

This runbook defines the operational procedure for Gheras V1. It does not authorize production activation. Any step requiring live credentials, provider-side changes, deployment, DNS/network ingress, or publication remains behind the corresponding Human Gate.

## 1. Non-negotiable invariants

1. Gheras never generates, rewrites, summarizes, or translates FATWA content.
2. Religious-possible content routes through the governed FATWA path.
3. FAQ publication uses only an active approved FAQ entry.
4. Supervisor publication uses only an accepted durable human response.
5. FATWA publication uses only an externally approved attributed result and the configured destination policy.
6. Machine moderation `HUMAN_REVIEW` never becomes routing permission without a durable human `allow_routing` decision.
7. `dispatching` and `uncertain` outbound actions are never blindly retried.
8. Secrets are never committed, pasted into tickets/chat, or written to application logs.
9. Production promotion requires the relevant CI and independent-review gates.

## 2. Deployment target decision — HOLD until selected

Before production activation, record the target environment and approve:

- operating system and CPU architecture;
- Python 3.12 patch version/runtime image;
- persistent volume location for SQLite;
- process model: exactly one authoritative write-capable application deployment unless a separately validated SQLite coordination design exists;
- ingress termination/proxy and TLS ownership;
- backup destination and retention;
- monitoring/alerting destination;
- secret store and rotation ownership.

Do not create target wheel/hash locks until OS/architecture are fixed.

## 3. Database requirements

The SQLite database is the durable source of truth for routing state, human review state, supervisor/FATWA state, Shadow observations, publication intent, and publication reconciliation.

Required operating conditions:

- database file lives on persistent storage;
- SQLite WAL mode remains enabled for normal write connections;
- filesystem must support SQLite locking semantics;
- do not place the live database on an eventually consistent object store;
- do not copy only the main `.db` file from a running WAL database as a backup;
- use the SQLite backup API provided by `app.operations.database.create_verified_backup` or an equivalently validated SQLite-native snapshot procedure.

### Pre-change backup

Before deployment, migration, dependency/runtime change, or controlled cutover:

1. verify operational readiness;
2. create a new backup path that does not already exist;
3. run the verified backup operation;
4. require `integrity_check = ok` and zero foreign-key violations;
5. store the resulting SHA-256 and backup timestamp in the change record;
6. protect the backup using the selected retention/access policy.

The backup helper refuses implicit overwrite and removes a newly created backup if verification fails.

### Restore

Restore is a maintenance-mode operation and must never be performed over a running writer.

1. stop all Gheras write-capable processes;
2. preserve the current database as a separate incident snapshot;
3. validate the candidate backup with SQLite `integrity_check` and `foreign_key_check`;
4. replace the database only through the environment-specific controlled restore procedure;
5. start one instance in non-publishing/readiness mode first;
6. verify counts, reconciliation holds, and Shadow state;
7. only then proceed to the approved activation mode.

A restore does not prove provider-side publication state. Any `dispatching` or `uncertain` action still requires reconciliation.

## 4. Operational readiness snapshot

`OperationalReadinessService` is read-only and selects counts/state only. It does not select inbound comment text, approved reply text, credentials, idempotency keys, or provider result identifiers.

Review at minimum:

- SQLite integrity and foreign-key violations;
- inbound totals and failed states;
- pending moderation human reviews;
- supervisor pending/awaiting queues;
- FATWA pending/awaiting queues;
- publication pending/dispatching/uncertain/succeeded counts;
- Shadow evaluation count.

`requires_operator_attention` is true when:

- SQLite integrity fails;
- foreign-key violations exist;
- publication actions remain `dispatching`;
- publication actions remain `uncertain`;
- terminal inbound failures exist.

Expected human/supervisor/FATWA waiting queues are visible but are not automatically treated as database/system corruption.

## 5. Publication reconciliation

### Rule

Never retry a `dispatching` or `uncertain` publication solely because a timeout, crash, or exception occurred. The provider may already have accepted the reply.

### Inventory

`OperationalReadinessService.publication_reconciliation_items()` exposes only:

- internal action ID;
- platform;
- held status;
- last-updated timestamp.

It does not expose comment/reply text.

### Provider-side verification

For each held action, an authorized operator must determine one of only two outcomes using provider-side evidence:

#### A. Confirmed succeeded

Use only when the provider confirms the reply exists and provides a stable external result identifier.

Record:

- action ID;
- operator reference;
- evidence reference;
- unique external reconciliation key;
- stable external result ID.

The atomic reconciliation transaction records immutable evidence and moves the action to `succeeded`. Future dispatcher calls return the durable success and do not call the provider again.

#### B. Confirmed not sent

Use only when provider-side evidence proves the original attempt produced no external side effect.

Record:

- action ID;
- operator reference;
- evidence reference;
- unique external reconciliation key.

The atomic reconciliation transaction records the evidence and returns the action to `pending`. This does **not** itself publish anything. A later explicit dispatcher operation may attempt publication again.

### If provider outcome cannot be proven

Leave the action held. Do not infer success and do not reset it to pending.

## 6. Logging and redaction

Production logs must be structured and content-minimized.

Allowed operational fields include:

- internal event/action IDs;
- platform;
- route/outcome/status codes;
- adapter/client names and version identifiers;
- retry/attempt counts;
- timestamps and latency;
- sanitized error codes.

Do not log:

- access tokens, app secrets, webhook secrets, API keys;
- authorization headers or signed URLs;
- full inbound comment text by default;
- FAQ/supervisor/FATWA answer text by default;
- provider request/response bodies containing user content;
- raw exception objects when they may contain transport/request data.

Provider errors exposed to logs/monitoring must use the existing sanitized error boundary.

## 7. Monitoring and alerts

The production environment should alert on state/count transitions rather than content.

Recommended alert classes:

- database integrity/foreign-key failure: critical;
- any `uncertain` publication: high;
- `dispatching` action older than the approved reconciliation threshold: high;
- terminal inbound failure: high;
- repeated retryable failures above threshold: medium/high;
- supervisor/FATWA queue age above approved service target: medium;
- webhook authentication/signature failures above baseline: medium/high;
- provider rate-limit/authentication failures: high;
- backup verification failure: critical.

Threshold values belong to the deployment environment and must be approved before live activation.

## 8. Backup retention

The final retention schedule is an owner/environment decision. The selected policy must define:

- backup frequency;
- pre-deploy/pre-migration backup requirement;
- retention periods;
- encryption/access controls;
- off-host or independent-failure-domain copy where appropriate;
- periodic restore test cadence;
- deletion procedure.

Do not claim backup readiness until at least one restore rehearsal has been completed in staging using the selected production-equivalent storage/runtime.

## 9. Ingress/network controls

Before live registration of provider webhooks or polling:

- TLS termination is defined;
- only required public endpoints are exposed;
- Meta webhook signature verification is enabled;
- Telegram webhook secret validation is enabled;
- provider verify tokens/secrets remain outside source control;
- request-size/time limits are defined at the ingress layer;
- rate limiting/abuse controls are configured where applicable;
- provider callback URLs point to staging first, not production, during validation.

## 10. Shadow-before-publish procedure

Production-like staging must run Shadow Mode before live publication is permitted.

1. use representative sandbox/staging or safely replayed traffic;
2. keep publication disabled;
3. collect counts for `would_publish`, `would_wait_human`, `would_route_fatwa`, `not_ready`, and `blocked`;
4. inspect unexpected distributions and representative cases through authorized review paths;
5. resolve unexplained routing/moderation defects;
6. record evaluator version and dataset/time window;
7. obtain the required activation approval only after the Shadow gate passes.

## 11. Cutover procedure

Cutover remains a Human Gate. When authorized:

1. confirm legacy path remains retired;
2. confirm reviewed/passed code is the exact release SHA;
3. confirm dependency/SCA gate is current for the release;
4. create and verify a pre-cutover database backup;
5. confirm all required secrets/scopes through the secret store without exposing values;
6. confirm reconciliation inventory is understood and no unexplained publication holds remain;
7. deploy in non-publishing or Shadow mode first;
8. validate health/readiness and provider ingress;
9. validate supervisor/FATWA integration in the approved staging/live-safe sequence;
10. enable publishing only after the explicit activation decision.

## 12. Rollback procedure

Rollback must prioritize duplicate-reply prevention over speed.

1. disable new publication dispatch first;
2. preserve the live database and logs/metrics needed for reconciliation;
3. inventory `dispatching` and `uncertain` actions;
4. do not retry those actions from the previous or rollback version;
5. if code rollback is sufficient, keep the current durable database unless a schema/data rollback is specifically required and proven safe;
6. if database restore is required, follow the maintenance-mode restore procedure and reconcile external side effects separately;
7. resume in Shadow/non-publishing mode before re-enabling publication.

## 13. Incident priorities

Order of response:

1. stop uncontrolled publication/side effects;
2. protect secrets and durable evidence;
3. preserve database state and obtain a verified snapshot;
4. reconcile potentially duplicated/uncertain external actions;
5. restore routing/human-review/FATWA safety invariants;
6. only then restore normal throughput.

## 14. Live activation HOLDs

This runbook does not close the following by itself:

- deployment target selection;
- production secret provisioning/scopes;
- real provider sandbox validation;
- supervised FATWA live integration;
- production-equivalent backup/restore rehearsal;
- staging Shadow acceptance;
- monitoring/alert threshold approval;
- independent review and promotion to `main`;
- explicit production publication activation.
