from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.adapters.models.contracts import StructuredDecisionRequest
from app.ingress.common import IngressConflict
from app.integrations.live.activation import issue_sandbox_execution_permit
from app.operations.replay import ReplayCorpusError, load_replay_corpus, run_replay_corpus
from app.runtime.prelive import create_prelive_sandbox_runtime


class StaticDecisionClient:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls: list[StructuredDecisionRequest] = []

    async def request(self, request: StructuredDecisionRequest) -> object:
        self.calls.append(request)
        return self.output


def _moderation_output() -> dict[str, object]:
    return {
        "verdict": "safe",
        "severity": "none",
        "confidence": 0.99,
        "categories": [],
        "text_assessed": True,
        "media_assessed": False,
    }


def _classification_output() -> dict[str, object]:
    return {
        "proposed_route": "FAQ",
        "confidence": 0.99,
        "religious_possible": False,
        "faq_key": "registration.status",
    }


def _runtime(
    tmp_path: Path,
    *,
    moderation_output: object | None = None,
    evaluator_version: str = "phase20-test-v1",
):
    moderation = StaticDecisionClient(
        _moderation_output() if moderation_output is None else moderation_output
    )
    classification = StaticDecisionClient(_classification_output())
    runtime = create_prelive_sandbox_runtime(
        tmp_path / "router.db",
        permit=issue_sandbox_execution_permit(purpose="sandbox_validation"),
        moderation_client=moderation,
        classification_client=classification,
        meta_app_secret="phase20-meta-test",
        meta_verify_token="phase20-meta-verify",
        telegram_webhook_secret="Phase20_Telegram-Test",
        evaluator_version=evaluator_version,
    )
    return runtime, moderation, classification


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def _record(*, key: str = "replay-1", text: str = "When does registration start?") -> dict[str, object]:
    return {
        "platform": "telegram",
        "external_event_key": key,
        "external_comment_id": key,
        "text": text,
    }


def test_loader_binds_exact_file_digest_and_redacts_repr(tmp_path: Path) -> None:
    corpus_path = tmp_path / "corpus.jsonl"
    source_text = "source text must not appear in reports"
    _write_jsonl(corpus_path, [_record(text=source_text)])

    corpus = load_replay_corpus(corpus_path)

    assert corpus.manifest.record_count == 1
    assert corpus.manifest.by_platform == {"telegram": 1}
    assert len(corpus.manifest.sha256) == 64
    assert source_text not in repr(corpus)
    assert source_text not in repr(corpus.records[0])


def test_loader_rejects_duplicate_json_keys_and_unknown_fields(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(
        '{"platform":"telegram","platform":"facebook",'
        '"external_event_key":"x","text":"hello"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ReplayCorpusError, match="duplicate keys"):
        load_replay_corpus(duplicate)

    unknown = tmp_path / "unknown.jsonl"
    _write_jsonl(unknown, [{**_record(), "provider_payload": "not-allowed"}])
    with pytest.raises(ReplayCorpusError, match="unsupported replay fields"):
        load_replay_corpus(unknown)


def test_replay_is_idempotent_and_never_creates_publication_actions(tmp_path: Path) -> None:
    corpus_path = tmp_path / "corpus.jsonl"
    record = _record()
    _write_jsonl(corpus_path, [record, record])
    corpus = load_replay_corpus(corpus_path)
    runtime, moderation, classification = _runtime(tmp_path)

    report = asyncio.run(run_replay_corpus(runtime, corpus))

    assert report.presented_count == 2
    assert report.unique_event_count == 1
    assert report.duplicate_count == 1
    assert report.shadow_total == 1
    assert report.shadow_by_platform == {"telegram": 1}
    assert report.shadow_by_outcome == {"would_wait_human": 1}
    assert runtime.publications.count_actions() == 0
    assert len(moderation.calls) == 1
    assert len(classification.calls) == 1


def test_replay_persists_pending_moderation_review_as_shadow_evidence(tmp_path: Path) -> None:
    corpus_path = tmp_path / "corpus.jsonl"
    _write_jsonl(corpus_path, [_record(text="Needs human review")])
    corpus = load_replay_corpus(corpus_path)
    malformed_moderation = {"verdict": "safe", "extra": "invalid"}
    runtime, moderation, classification = _runtime(
        tmp_path,
        moderation_output=malformed_moderation,
        evaluator_version="phase20-human-review-v1",
    )

    report = asyncio.run(run_replay_corpus(runtime, corpus))

    assert report.shadow_total == 1
    assert report.shadow_by_route == {"none": 1}
    assert report.shadow_by_outcome == {"would_wait_human": 1}
    assert runtime.shadows.count() == 1
    assert runtime.publications.count_actions() == 0
    assert len(moderation.calls) == 1
    assert classification.calls == []


def test_replay_rejects_duplicate_identity_with_changed_semantics(tmp_path: Path) -> None:
    corpus_path = tmp_path / "corpus.jsonl"
    _write_jsonl(
        corpus_path,
        [
            _record(key="same-key", text="first text"),
            _record(key="same-key", text="different text"),
        ],
    )
    corpus = load_replay_corpus(corpus_path)
    runtime, _, _ = _runtime(tmp_path)

    with pytest.raises(IngressConflict, match="identity conflicts"):
        asyncio.run(run_replay_corpus(runtime, corpus))

    assert runtime.publications.count_actions() == 0
