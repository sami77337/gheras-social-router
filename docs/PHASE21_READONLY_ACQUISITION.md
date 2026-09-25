# Phase 21 — Read-Only Historical Comment Acquisition

## Status

**ENGINEERING PREPARATION: PASS. NO REAL PROVIDER CALL HAS BEEN EXECUTED.**

Phase 21 prepares private historical acquisition so HG-09 can continue as soon as approved source access is available. It does not authorize or perform live collection by itself.

## Safety boundary

- Acquisition modules expose only read operations.
- Provider HTTP calls use `GET` only.
- Every provider request still requires an explicit `SandboxExecutionPermit`.
- HTTP clients are injected; automated tests use `httpx.MockTransport`.
- API keys and access tokens are accepted at runtime only and are never written to replay files, manifests, exceptions, or Git.
- Generated replay JSONL and private evidence paths remain excluded by `.gitignore`.
- Author identities are intentionally omitted from generated replay records.
- Pagination and accumulated record counts are bounded and fail closed instead of silently truncating evidence.
- Telegram ZIP imports bound both archive size and total uncompressed messages-HTML size before parsing, and conflicting duplicate message IDs fail closed.
- Replay JSONL output is validated through the Phase 20 strict loader before atomically replacing the requested target path.
- Merging preserves the original Phase 20 platform/event identity exactly, rejects semantic conflicts, and intentionally removes author identity from the emitted merged corpus.
- Meta pagination uses cursors on the fixed allowlisted Graph host; raw `paging.next` URLs are not followed.

## Telegram

Telegram Desktop HTML exports can be converted fully offline:

    python scripts/ops_import_telegram_export.py private-replay/telegram-export.zip private-replay/telegram.replay.jsonl

The importer reads `messages*.html`, excludes Telegram service records, omits sender names, and writes the same Phase 20 replay schema.

## YouTube

The historical reader uses `GET /youtube/v3/commentThreads` with `allThreadsRelatedToChannelId`, then `GET /youtube/v3/comments` when the thread response does not include every reply.

At execution time only, configure the restricted API key in the local environment and run:

    set GHERAS_YOUTUBE_API_KEY=...
    python scripts/ops_collect_youtube_comments.py --channel-id YOUR_CHANNEL_ID --output private-replay/youtube.replay.jsonl --confirm-read-only-provider-call

Do not put the key in the command line, repository, screenshots, or chat.

## Facebook and Instagram

The Meta historical reader operates only on explicit post/media identifiers. It reads top-level comments and their direct replies using Graph API GET requests.

At execution time only:

    set GHERAS_META_ACCESS_TOKEN=...
    python scripts/ops_collect_meta_comments.py --platform facebook --source-id POST_ID --api-version APPROVED_GRAPH_VERSION --output private-replay/facebook.replay.jsonl --confirm-read-only-provider-call

For Instagram use `--platform instagram` and one or more `--source-id MEDIA_ID` arguments.

The actual token/scopes and approved Graph API version remain provider-side Human Gates and are not selected or stored by Phase 21.

## Merge

After platform corpora exist:

    python scripts/ops_merge_replay_corpora.py private-replay/telegram.replay.jsonl private-replay/youtube.replay.jsonl private-replay/facebook.replay.jsonl private-replay/instagram.replay.jsonl --output private-replay/gheras-representative.replay.jsonl

The merge re-parses every input through the Phase 20 strict loader, preserves the original event identity instead of reconstructing it, omits author identity from the emitted corpus, and rejects semantic conflicts for the same platform/event identity.

## What remains

Phase 21 can be reviewed as engineering preparation without credentials. HG-09 remains HOLD until real representative data is collected, corpus identity is recorded, Shadow replay is executed with publication disabled, anomalies are reviewed, and a final PASS/HOLD/REJECT decision is recorded.

## Continuation hardening

A continuation review found two pre-lock weaknesses that were corrected before the engineering lock was renewed:

- the Telegram ZIP importer bounded each member but did not bound the aggregate uncompressed HTML size;
- the corpus merge helper reconstructed Phase 20 identities through `AcquiredComment`, which could rewrite an otherwise valid opaque `external_event_key`.

The hardening also moves record-count checks into provider collection loops and adds regression coverage for the corrected fail-closed behavior.

## Engineering lock evidence

- PR: #49 (stacked on Phase 20; open/unmerged)
- reviewed code head before this documentation lock: `e9851a6e798af99f5ee2e4f30c0beaff60481a19`
- full CI run: `36136526141` — PASS
- production lock metadata: PASS
- dependency consistency: PASS
- production dependency audit: PASS
- build-tool audit: PASS
- CI/development audit: PASS
- production-environment reproduction: PASS
- Ruff: PASS
- Mypy: PASS
- Pytest: PASS
- superseded CI run `36136385611` failed only because the newly added ZIP-bound regression fixture set the test byte limit below the ZIP container size; the fixture was corrected and the final run above passed
- submitted independent review: none at lock time
- real provider execution: not performed
