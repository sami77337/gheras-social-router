"""Strict private approved-FAQ snapshot loading for representative Shadow runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.persistence.faq_repository import FAQRepository

_MAX_SNAPSHOT_BYTES = 5_000_000
_MAX_ENTRIES = 2_000
_MAX_ANSWER_LENGTH = 16_000
_REQUIRED_KEYS = frozenset(
    {
        "faq_key",
        "answer_text",
        "source_ref",
        "approved_by",
        "approved_at",
    }
)


class FAQSnapshotError(ValueError):
    """Raised when an approved FAQ snapshot violates the replay contract."""


@dataclass(frozen=True, slots=True)
class ApprovedFAQSnapshotEntry:
    faq_key: str
    answer_text: str
    source_ref: str
    approved_by: str
    approved_at: datetime


@dataclass(frozen=True, slots=True)
class FAQSnapshotManifest:
    sha256: str
    size_bytes: int
    entry_count: int
    key_set_sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class ApprovedFAQSnapshot:
    manifest: FAQSnapshotManifest
    entries: tuple[ApprovedFAQSnapshotEntry, ...]

    def __repr__(self) -> str:
        return (
            "ApprovedFAQSnapshot("
            f"sha256={self.manifest.sha256!r}, "
            f"entry_count={self.manifest.entry_count}, content_redacted=True)"
        )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FAQSnapshotError("FAQ snapshot JSON object contains duplicate keys")
        result[key] = value
    return result


def _text(
    value: object,
    *,
    field: str,
    maximum: int,
    compact: bool = False,
) -> str:
    if not isinstance(value, str):
        raise FAQSnapshotError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise FAQSnapshotError(f"{field} is empty or exceeds maximum length")
    if compact and any(char.isspace() for char in normalized):
        raise FAQSnapshotError(f"{field} must not contain whitespace")
    return normalized


def _approved_at(value: object) -> datetime:
    raw = _text(value, field="approved_at", maximum=64)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise FAQSnapshotError("approved_at must be ISO-8601") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FAQSnapshotError("approved_at must include a timezone")
    return parsed


def _entry(value: object, *, line_number: int) -> ApprovedFAQSnapshotEntry:
    if not isinstance(value, dict):
        raise FAQSnapshotError(f"line {line_number}: FAQ record must be an object")
    keys = frozenset(value)
    if keys != _REQUIRED_KEYS:
        raise FAQSnapshotError(
            f"line {line_number}: FAQ record fields do not match the snapshot schema"
        )
    return ApprovedFAQSnapshotEntry(
        faq_key=_text(value["faq_key"], field="faq_key", maximum=128, compact=True),
        answer_text=_text(
            value["answer_text"],
            field="answer_text",
            maximum=_MAX_ANSWER_LENGTH,
        ),
        source_ref=_text(value["source_ref"], field="source_ref", maximum=512),
        approved_by=_text(value["approved_by"], field="approved_by", maximum=128),
        approved_at=_approved_at(value["approved_at"]),
    )


def load_approved_faq_snapshot(path: str | Path) -> ApprovedFAQSnapshot:
    """Validate the complete private FAQ snapshot before mutating any database."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    size = source.stat().st_size
    if size <= 0:
        raise FAQSnapshotError("FAQ snapshot must not be empty")
    if size > _MAX_SNAPSHOT_BYTES:
        raise FAQSnapshotError("FAQ snapshot exceeds maximum size")

    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise FAQSnapshotError("FAQ snapshot must be UTF-8 JSONL") from None

    entries: list[ApprovedFAQSnapshotEntry] = []
    seen_keys: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if len(entries) >= _MAX_ENTRIES:
            raise FAQSnapshotError("FAQ snapshot exceeds maximum entry count")
        try:
            value = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        except FAQSnapshotError:
            raise
        except (json.JSONDecodeError, RecursionError):
            raise FAQSnapshotError(f"line {line_number}: invalid JSON") from None
        parsed = _entry(value, line_number=line_number)
        if parsed.faq_key in seen_keys:
            raise FAQSnapshotError("FAQ snapshot contains duplicate faq_key values")
        seen_keys.add(parsed.faq_key)
        entries.append(parsed)

    if not entries:
        raise FAQSnapshotError("FAQ snapshot contains no entries")
    key_set_digest = hashlib.sha256(
        "\n".join(sorted(seen_keys)).encode()
    ).hexdigest()
    return ApprovedFAQSnapshot(
        manifest=FAQSnapshotManifest(
            sha256=digest,
            size_bytes=size,
            entry_count=len(entries),
            key_set_sha256=key_set_digest,
        ),
        entries=tuple(entries),
    )


def seed_approved_faq_snapshot(
    repository: FAQRepository,
    snapshot: ApprovedFAQSnapshot,
) -> FAQSnapshotManifest:
    """Seed one validated active FAQ snapshot into an otherwise fresh replay store."""

    if repository.count_entries() != 0:
        raise FAQSnapshotError("FAQ replay store must be empty before snapshot seeding")
    for entry in snapshot.entries:
        repository.create_version(
            faq_key=entry.faq_key,
            answer_text=entry.answer_text,
            source_ref=entry.source_ref,
            approved_by=entry.approved_by,
            approved_at=entry.approved_at,
            activate=True,
        )
    if repository.count_entries() != snapshot.manifest.entry_count:
        raise RuntimeError("FAQ snapshot seed count does not reconcile")
    return snapshot.manifest
