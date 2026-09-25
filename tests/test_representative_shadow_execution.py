from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.adapters.models.contracts import StructuredDecisionRequest
from app.integrations.live.activation import issue_sandbox_execution_permit
from app.operations.faq_snapshot import (
    FAQSnapshotError,
    load_approved_faq_snapshot,
)
from app.operations.representative_shadow import (
    RepresentativeShadowError,
    execute_representative_shadow,
)


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


def _write_corpus(path: Path, text: str) -> None:
    path.write_text(
        json.dumps(
            {
                "platform": "telegram",
                "external_event_key": "telegram:representative:1",
                "external_comment_id": "representative-1",
                "text": text,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _write_faq(path: Path, answer: str) -> None:
    path.write_text(
        json.dumps(
            {
                "faq_key": "registration.status",
                "answer_text": answer,
                "source_ref": "approved-source-1",
                "approved_by": "approved-reviewer",
                "approved_at": "2026-09-01T10:00:00+03:00",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def test_faq_snapshot_is_strict_and_content_redacted(tmp_path: Path) -> None:
    source = tmp_path / "approved.faq.jsonl"
    private_answer = "Private approved answer"
    _write_faq(source, private_answer)

    snapshot = load_approved_faq_snapshot(source)

    assert snapshot.manifest.entry_count == 1
    assert len(snapshot.manifest.sha256) == 64
    assert len(snapshot.manifest.key_set_sha256) == 64
    assert private_answer not in repr(snapshot)
    assert private_answer not in repr(snapshot.entries[0])
    assert "approved-reviewer" not in repr(snapshot.entries[0])


def test_faq_snapshot_rejects_duplicate_key_and_naive_timestamp(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.faq.jsonl"
    duplicate.write_text(
        '{"faq_key":"one","faq_key":"two","answer_text":"a",'
        '"source_ref":"s","approved_by":"r",'
        '"approved_at":"2026-09-01T10:00:00+03:00"}\n',
        encoding="utf-8",
    )
    with pytest.raises(FAQSnapshotError, match="duplicate keys"):
        load_approved_faq_snapshot(duplicate)

    naive = tmp_path / "naive.faq.jsonl"
    naive.write_text(
        '{"faq_key":"one","answer_text":"a","source_ref":"s",'
        '"approved_by":"r","approved_at":"2026-09-01T10:00:00"}\n',
        encoding="utf-8",
    )
    with pytest.raises(FAQSnapshotError, match="timezone"):
        load_approved_faq_snapshot(naive)


def test_representative_shadow_is_content_free_and_non_publishing(tmp_path: Path) -> None:
    source_text = "Private representative comment"
    approved_answer = "Private approved answer"
    corpus = tmp_path / "representative.replay.jsonl"
    faq = tmp_path / "approved.faq.jsonl"
    database = tmp_path / "representative.db"
    _write_corpus(corpus, source_text)
    _write_faq(faq, approved_answer)

    moderation = StaticDecisionClient(_moderation_output())
    classification = StaticDecisionClient(_classification_output())
    evidence = asyncio.run(
        execute_representative_shadow(
            corpus_path=corpus,
            database_path=database,
            permit=issue_sandbox_execution_permit(purpose="sandbox_validation"),
            moderation_client=moderation,
            classification_client=classification,
            evaluator_version="hg09-test-v1",
            release_sha="a" * 40,
            model_id="test-model-v1",
            faq_snapshot_path=faq,
        )
    )

    serialized = json.dumps(
        {
            "release_sha": evidence.release_sha,
            "model_id": evidence.model_id,
            "evaluator_version": evidence.evaluator_version,
            "corpus_sha256": evidence.corpus_sha256,
            "corpus_record_count": evidence.corpus_record_count,
            "faq_snapshot_sha256": (
                evidence.faq_snapshot.sha256 if evidence.faq_snapshot else None
            ),
            "shadow_total": evidence.replay.shadow_total,
            "shadow_by_outcome": evidence.replay.shadow_by_outcome,
        },
        sort_keys=True,
    )
    assert evidence.corpus_record_count == 1
    assert evidence.replay.shadow_total == 1
    assert evidence.faq_snapshot is not None
    assert evidence.faq_snapshot.entry_count == 1
    assert len(moderation.calls) == 1
    assert len(classification.calls) == 1
    assert source_text not in serialized
    assert approved_answer not in serialized


def test_representative_shadow_requires_fresh_database(tmp_path: Path) -> None:
    corpus = tmp_path / "representative.replay.jsonl"
    database = tmp_path / "existing.db"
    _write_corpus(corpus, "private comment")
    database.write_bytes(b"already exists")

    client = StaticDecisionClient(_moderation_output())
    with pytest.raises(RepresentativeShadowError, match="must not already exist"):
        asyncio.run(
            execute_representative_shadow(
                corpus_path=corpus,
                database_path=database,
                permit=issue_sandbox_execution_permit(purpose="sandbox_validation"),
                moderation_client=client,
                classification_client=client,
                evaluator_version="hg09-test-v2",
                release_sha="b" * 40,
                model_id="test-model-v1",
            )
        )
    assert client.calls == []



def test_representative_shadow_rejects_invalid_evaluator_version(tmp_path: Path) -> None:
    corpus = tmp_path / "representative.replay.jsonl"
    database = tmp_path / "representative.db"
    _write_corpus(corpus, "private comment")

    client = StaticDecisionClient(_moderation_output())
    with pytest.raises(RepresentativeShadowError, match="evaluator_version is invalid"):
        asyncio.run(
            execute_representative_shadow(
                corpus_path=corpus,
                database_path=database,
                permit=issue_sandbox_execution_permit(purpose="sandbox_validation"),
                moderation_client=client,
                classification_client=client,
                evaluator_version="invalid evaluator version",
                release_sha="c" * 40,
                model_id="test-model-v1",
            )
        )
    assert client.calls == []
    assert not database.exists()
