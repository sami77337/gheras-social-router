"""Content-free orchestration for one representative private Shadow evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.adapters.models.contracts import StructuredDecisionClient
from app.integrations.live.activation import SandboxExecutionPermit
from app.operations.faq_snapshot import (
    FAQSnapshotManifest,
    load_approved_faq_snapshot,
    seed_approved_faq_snapshot,
)
from app.operations.replay import ReplayRunReport, load_replay_corpus, run_replay_corpus
from app.runtime.prelive import create_prelive_sandbox_runtime

_RELEASE_SHA = re.compile(r"^[0-9a-f]{40}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class RepresentativeShadowError(RuntimeError):
    """Raised when representative execution preconditions are not satisfied."""


@dataclass(frozen=True, slots=True)
class RepresentativeShadowEvidence:
    release_sha: str
    model_id: str
    evaluator_version: str
    corpus_sha256: str
    corpus_record_count: int
    faq_snapshot: FAQSnapshotManifest | None
    replay: ReplayRunReport


def _release_sha(value: str) -> str:
    normalized = value.strip().lower()
    if not _RELEASE_SHA.fullmatch(normalized):
        raise RepresentativeShadowError("release_sha must be a full 40-character Git SHA")
    return normalized


def _model_id(value: str) -> str:
    normalized = value.strip()
    if not _MODEL_ID.fullmatch(normalized):
        raise RepresentativeShadowError("model_id is invalid")
    return normalized


async def execute_representative_shadow(
    *,
    corpus_path: str | Path,
    database_path: str | Path,
    permit: SandboxExecutionPermit | None,
    moderation_client: StructuredDecisionClient,
    classification_client: StructuredDecisionClient,
    evaluator_version: str,
    release_sha: str,
    model_id: str,
    faq_snapshot_path: str | Path | None = None,
) -> RepresentativeShadowEvidence:
    """Execute one fresh, non-publishing representative Shadow run."""

    database = Path(database_path)
    if database.exists():
        raise RepresentativeShadowError(
            "representative Shadow database must not already exist"
        )

    release = _release_sha(release_sha)
    model = _model_id(model_id)
    corpus = load_replay_corpus(corpus_path)

    runtime = create_prelive_sandbox_runtime(
        database,
        permit=permit,
        moderation_client=moderation_client,
        classification_client=classification_client,
        meta_app_secret="replay_inert_meta_secret",
        meta_verify_token="replay_inert_meta_verify",
        telegram_webhook_secret="Replay_Inert_Telegram_Secret",
        publishers={},
        evaluator_version=evaluator_version,
    )

    faq_manifest: FAQSnapshotManifest | None = None
    if faq_snapshot_path is not None:
        snapshot = load_approved_faq_snapshot(faq_snapshot_path)
        faq_manifest = seed_approved_faq_snapshot(runtime.faqs, snapshot)

    replay = await run_replay_corpus(runtime, corpus)
    if runtime.publications.count_actions() != 0:
        raise RepresentativeShadowError(
            "representative Shadow execution created publication actions"
        )

    return RepresentativeShadowEvidence(
        release_sha=release,
        model_id=model,
        evaluator_version=evaluator_version,
        corpus_sha256=corpus.manifest.sha256,
        corpus_record_count=corpus.manifest.record_count,
        faq_snapshot=faq_manifest,
        replay=replay,
    )
