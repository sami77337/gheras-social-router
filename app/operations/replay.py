"""Private representative-corpus loading and non-publishing Shadow replay."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.events import NormalizedInboundEvent, Platform
from app.ingress.common import ExactIngestionCollector
from app.operations.database import inspect_database
from app.operations.shadow_evidence import ShadowEvidenceReport, ShadowEvidenceService
from app.runtime.prelive import PreLiveSandboxRuntime

_MAX_CORPUS_BYTES = 20_000_000
_MAX_RECORDS = 20_000
_MAX_ID_LENGTH = 512
_MAX_TEXT_LENGTH = 16_000
_ALLOWED_KEYS = frozenset(
    {
        "platform",
        "external_event_key",
        "external_event_id",
        "external_comment_id",
        "external_post_id",
        "author_id",
        "text",
    }
)


class ReplayCorpusError(ValueError):
    """Raised when a private replay corpus violates the strict local contract."""


class ReplayInvariantError(RuntimeError):
    """Raised when replay execution violates a non-publishing/evidence invariant."""


@dataclass(frozen=True, slots=True, repr=False)
class ReplayCorpusRecord:
    """One private normalized text record. Repr intentionally omits source content."""

    platform: Platform
    external_event_key: str
    text: str
    external_event_id: str | None = None
    external_comment_id: str | None = None
    external_post_id: str | None = None
    author_id: str | None = None

    def __repr__(self) -> str:
        return f"ReplayCorpusRecord(platform={self.platform.value!r}, content_redacted=True)"

    def to_event(self) -> NormalizedInboundEvent:
        return NormalizedInboundEvent(
            platform=self.platform,
            external_event_key=self.external_event_key,
            external_event_id=self.external_event_id,
            external_comment_id=self.external_comment_id,
            external_post_id=self.external_post_id,
            author_id=self.author_id,
            text=self.text,
        )


@dataclass(frozen=True, slots=True)
class ReplayCorpusManifest:
    """Content-free identity and shape of one exact private corpus file."""

    sha256: str
    size_bytes: int
    record_count: int
    by_platform: dict[str, int]


@dataclass(frozen=True, slots=True, repr=False)
class ReplayCorpus:
    """Validated private corpus plus content-free manifest."""

    manifest: ReplayCorpusManifest
    records: tuple[ReplayCorpusRecord, ...]

    def __repr__(self) -> str:
        return (
            "ReplayCorpus("
            f"sha256={self.manifest.sha256!r}, "
            f"record_count={self.manifest.record_count}, content_redacted=True)"
        )


@dataclass(frozen=True, slots=True)
class ReplayRunReport:
    """Content-free evidence binding one private corpus to one Shadow run."""

    corpus_sha256: str
    corpus_size_bytes: int
    presented_count: int
    unique_event_count: int
    duplicate_count: int
    corpus_by_platform: dict[str, int]
    evaluator_version: str
    shadow_total: int
    shadow_by_platform: dict[str, int]
    shadow_by_route: dict[str, int]
    shadow_by_outcome: dict[str, int]
    shadow_evidence_sha256: str
    first_created_at: str
    last_created_at: str


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReplayCorpusError("replay JSON object contains duplicate keys")
        result[key] = value
    return result


def _required_text(value: Any, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ReplayCorpusError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ReplayCorpusError(f"{field} must not be empty")
    if len(normalized) > maximum:
        raise ReplayCorpusError(f"{field} exceeds maximum length")
    return normalized


def _optional_text(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field=field, maximum=_MAX_ID_LENGTH)


def _record_from_object(value: object, *, line_number: int) -> ReplayCorpusRecord:
    if not isinstance(value, dict):
        raise ReplayCorpusError(f"line {line_number}: replay record must be a JSON object")
    unknown = set(value) - _ALLOWED_KEYS
    if unknown:
        raise ReplayCorpusError(f"line {line_number}: unsupported replay fields")
    try:
        platform_raw = _required_text(
            value.get("platform"),
            field="platform",
            maximum=32,
        )
        platform = Platform(platform_raw)
    except ValueError:
        raise ReplayCorpusError(f"line {line_number}: unsupported platform") from None

    event_key = _required_text(
        value.get("external_event_key"),
        field="external_event_key",
        maximum=_MAX_ID_LENGTH,
    )
    text = _required_text(value.get("text"), field="text", maximum=_MAX_TEXT_LENGTH)
    return ReplayCorpusRecord(
        platform=platform,
        external_event_key=event_key,
        external_event_id=_optional_text(value.get("external_event_id"), field="external_event_id"),
        external_comment_id=_optional_text(
            value.get("external_comment_id"), field="external_comment_id"
        ),
        external_post_id=_optional_text(value.get("external_post_id"), field="external_post_id"),
        author_id=_optional_text(value.get("author_id"), field="author_id"),
        text=text,
    )


def load_replay_corpus(path: str | Path) -> ReplayCorpus:
    """Load one bounded UTF-8 JSONL corpus and bind it to the exact file SHA-256."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    size = source.stat().st_size
    if size <= 0:
        raise ReplayCorpusError("replay corpus must not be empty")
    if size > _MAX_CORPUS_BYTES:
        raise ReplayCorpusError("replay corpus exceeds maximum size")

    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ReplayCorpusError("replay corpus must be UTF-8 JSONL") from None

    records: list[ReplayCorpusRecord] = []
    by_platform = {platform.value: 0 for platform in Platform}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if len(records) >= _MAX_RECORDS:
            raise ReplayCorpusError("replay corpus exceeds maximum record count")
        try:
            value = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        except ReplayCorpusError:
            raise
        except (json.JSONDecodeError, RecursionError):
            raise ReplayCorpusError(f"line {line_number}: invalid JSON") from None
        record = _record_from_object(value, line_number=line_number)
        records.append(record)
        by_platform[record.platform.value] += 1

    if not records:
        raise ReplayCorpusError("replay corpus contains no records")
    manifest = ReplayCorpusManifest(
        sha256=digest,
        size_bytes=size,
        record_count=len(records),
        by_platform={key: count for key, count in by_platform.items() if count},
    )
    return ReplayCorpus(manifest=manifest, records=tuple(records))


def _shadow_count_for_version(runtime: PreLiveSandboxRuntime, evaluator_version: str) -> int:
    with runtime.database.connect_readonly() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM shadow_evaluations WHERE evaluator_version = ?",
            (evaluator_version,),
        ).fetchone()
    return int(row["count"]) if row is not None else 0


def _report_to_run(
    *,
    corpus: ReplayCorpus,
    unique_event_count: int,
    duplicate_count: int,
    evaluator_version: str,
    evidence: ShadowEvidenceReport,
) -> ReplayRunReport:
    return ReplayRunReport(
        corpus_sha256=corpus.manifest.sha256,
        corpus_size_bytes=corpus.manifest.size_bytes,
        presented_count=corpus.manifest.record_count,
        unique_event_count=unique_event_count,
        duplicate_count=duplicate_count,
        corpus_by_platform=dict(corpus.manifest.by_platform),
        evaluator_version=evaluator_version,
        shadow_total=evidence.total_evaluated,
        shadow_by_platform=dict(evidence.by_platform),
        shadow_by_route=dict(evidence.by_route),
        shadow_by_outcome=dict(evidence.by_outcome),
        shadow_evidence_sha256=evidence.evidence_sha256,
        first_created_at=evidence.first_created_at.isoformat(),
        last_created_at=evidence.last_created_at.isoformat(),
    )


async def run_replay_corpus(
    runtime: PreLiveSandboxRuntime,
    corpus: ReplayCorpus,
) -> ReplayRunReport:
    """Run a private corpus through pre-live routing while proving zero publication intent."""

    integrity = inspect_database(runtime.database)
    if not integrity.acceptable:
        raise ReplayInvariantError("database integrity preflight failed")

    evaluator_version = runtime.shadow.evaluator_version
    if _shadow_count_for_version(runtime, evaluator_version) != 0:
        raise ReplayInvariantError(
            "selected evaluator version already has Shadow evidence; use a fresh evaluator version"
        )

    publication_count_before = runtime.publications.count_actions()
    collector = ExactIngestionCollector(runtime.ingestion)
    unique_event_ids: set[str] = set()
    duplicate_count = 0

    for record in corpus.records:
        ingestion = collector.ingest(record.to_event())
        duplicate_count += int(not ingestion.created)
        event_id = ingestion.event.id
        unique_event_ids.add(event_id)
        processed = await runtime.process_event(event_id)

        persisted = runtime.shadows.get(event_id, evaluator_version)
        if persisted is None:
            persisted = runtime.shadow.evaluate(event_id)
        if persisted.outcome is not processed.shadow_outcome:
            raise ReplayInvariantError("processed outcome disagrees with durable Shadow evidence")

    publication_count_after = runtime.publications.count_actions()
    if publication_count_after != publication_count_before:
        raise ReplayInvariantError("replay created outbound publication actions")

    evidence = ShadowEvidenceService(runtime.database).report(evaluator_version)
    if evidence.total_evaluated != len(unique_event_ids):
        raise ReplayInvariantError(
            "Shadow evidence count does not match unique replay event universe"
        )

    return _report_to_run(
        corpus=corpus,
        unique_event_count=len(unique_event_ids),
        duplicate_count=duplicate_count,
        evaluator_version=evaluator_version,
        evidence=evidence,
    )
