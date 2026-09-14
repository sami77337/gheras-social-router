# Phase 20 — Private Representative Shadow Replay Runner

## Status

**ENGINEERING RUNNER: IMPLEMENTED.**

**HG-09 REPRESENTATIVE ACCEPTANCE: HOLD UNTIL A REAL APPROVED PRIVATE CORPUS IS EXECUTED AND REVIEWED.**

Phase 20 does not manufacture representative evidence. It prepares the local execution boundary required to run an approved private JSONL corpus through the existing pre-live routing graph while proving that no publication intent is created.

## Private corpus contract

The corpus is newline-delimited UTF-8 JSON. Each non-empty line is one object with:

- `platform`: one of `facebook`, `instagram`, `telegram`, `youtube`;
- `external_event_key`: stable event identity;
- `text`: non-empty source text;
- optional `external_event_id`, `external_comment_id`, `external_post_id`, `author_id`.

Unknown fields, duplicate JSON keys, unsupported platforms, invalid UTF-8, empty required fields, oversized files, and excessive record counts fail closed.

Raw representative corpus files must remain outside Git. `.gitignore` excludes `private-evidence/`, `private-replay/`, and `*.replay.jsonl`.

## Corpus identity

`load_replay_corpus()` computes SHA-256 over the exact source file bytes before processing and records only content-free manifest metadata:

- SHA-256;
- byte size;
- record count;
- platform composition.

`repr()` for corpus and record objects intentionally omits source text.

The local command:

```bash
python scripts/ops_replay_manifest.py private-replay/approved.replay.jsonl
```

emits only the content-free manifest.

## Replay execution

`run_replay_corpus(runtime, corpus)`:

1. verifies SQLite integrity;
2. requires the selected `evaluator_version` to have no pre-existing Shadow evidence, preventing aggregate contamination;
3. ingests through `ExactIngestionCollector`, so duplicate identities with changed semantics fail closed;
4. processes every accepted record through `PreLiveSandboxRuntime.process_event()`;
5. ensures pending moderation-human-review outcomes also become durable Shadow evidence for this replay;
6. verifies persisted Shadow outcome matches the processing result;
7. verifies the outbound publication-action count did not increase;
8. requires the version-scoped Shadow total to equal the unique replay event universe;
9. returns only content-free aggregate evidence linked to both corpus SHA-256 and Shadow evidence SHA-256.

Duplicate records with identical semantics are allowed and counted explicitly; they must resolve to one durable event and one Shadow record.

## What remains external

A Phase 20 unit/synthetic run is not HG-09 acceptance. Actual PASS still requires an approved representative staging or safely replayed private corpus, any approved model/provider configuration required for that evaluation, case-level anomaly review through a secure evidence path, and an explicit `PASS`, `HOLD`, or `REJECT` record under `docs/STAGING_SHADOW_EVALUATION_PROTOCOL.md`.

No real corpus, credential, provider call, webhook registration, deployment, or publication is introduced by this phase.
