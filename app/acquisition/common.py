"""Shared fail-closed contracts for read-only historical acquisition."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from app.domain.events import Platform
from app.operations.replay import load_replay_corpus

_MAX_ID_LENGTH = 512
_MAX_TEXT_LENGTH = 16_000
_MAX_RECORDS = 20_000


class AcquisitionProtocolError(ValueError):
    """Provider/export content does not satisfy the historical acquisition contract."""


class AcquisitionLimitExceeded(RuntimeError):
    """Acquisition would exceed an explicit operator-visible bound."""


def bounded_id(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise AcquisitionProtocolError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_ID_LENGTH or any(
        char.isspace() for char in normalized
    ):
        raise AcquisitionProtocolError(f"{field} is invalid")
    return normalized


def bounded_text(value: object, *, field: str = "text") -> str:
    if not isinstance(value, str):
        raise AcquisitionProtocolError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise AcquisitionProtocolError(f"{field} must not be empty")
    if len(normalized) > _MAX_TEXT_LENGTH:
        raise AcquisitionProtocolError(f"{field} exceeds maximum length")
    return normalized


@dataclass(frozen=True, slots=True, repr=False)
class AcquiredComment:
    """One normalized comment; repr deliberately omits content."""

    platform: Platform
    comment_id: str
    source_id: str
    text: str
    thread_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "comment_id",
            bounded_id(self.comment_id, field="comment_id"),
        )
        object.__setattr__(
            self,
            "source_id",
            bounded_id(self.source_id, field="source_id"),
        )
        object.__setattr__(self, "text", bounded_text(self.text))
        if self.thread_id is not None:
            object.__setattr__(
                self,
                "thread_id",
                bounded_id(self.thread_id, field="thread_id"),
            )

    def __repr__(self) -> str:
        return (
            "AcquiredComment("
            f"platform={self.platform.value!r}, comment_id={self.comment_id!r}, "
            "content_redacted=True)"
        )

    def replay_object(self) -> dict[str, str]:
        event_id = self.thread_id or self.comment_id
        return {
            "platform": self.platform.value,
            "external_event_key": f"{self.platform.value}:comment:{self.comment_id}",
            "external_event_id": event_id,
            "external_comment_id": self.comment_id,
            "external_post_id": self.source_id,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class AcquisitionBatch:
    """Content-free acquisition metadata plus private records."""

    platform: Platform
    source_ref_sha256: str
    comments: tuple[AcquiredComment, ...]

    @classmethod
    def build(
        cls,
        *,
        platform: Platform,
        source_ref: str,
        comments: tuple[AcquiredComment, ...],
    ) -> AcquisitionBatch:
        if not isinstance(source_ref, str):
            raise AcquisitionProtocolError("source_ref must be a string")
        source = source_ref.strip()
        if not source or len(source) > 2048:
            raise AcquisitionProtocolError("source_ref is invalid")
        if len(comments) > _MAX_RECORDS:
            raise AcquisitionLimitExceeded("acquisition exceeds maximum record count")
        if any(comment.platform is not platform for comment in comments):
            raise AcquisitionProtocolError("batch contains a mismatched platform")
        digest = hashlib.sha256(
            f"{platform.value}:{source}".encode()
        ).hexdigest()
        return cls(platform=platform, source_ref_sha256=digest, comments=comments)

    @property
    def record_count(self) -> int:
        return len(self.comments)

    def content_free_manifest(self) -> dict[str, object]:
        return {
            "platform": self.platform.value,
            "source_ref_sha256": self.source_ref_sha256,
            "record_count": self.record_count,
        }


def write_replay_jsonl(
    path: str | Path,
    comments: tuple[AcquiredComment, ...],
) -> dict[str, object]:
    """Write private replay JSONL, then re-parse it with Phase 20's strict loader."""

    if not comments:
        raise AcquisitionProtocolError("cannot write an empty acquisition")
    if len(comments) > _MAX_RECORDS:
        raise AcquisitionLimitExceeded("acquisition exceeds maximum record count")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for comment in comments:
            handle.write(
                json.dumps(
                    comment.replay_object(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )

    corpus = load_replay_corpus(target)
    return {
        "sha256": corpus.manifest.sha256,
        "size_bytes": corpus.manifest.size_bytes,
        "record_count": corpus.manifest.record_count,
        "by_platform": dict(corpus.manifest.by_platform),
    }
