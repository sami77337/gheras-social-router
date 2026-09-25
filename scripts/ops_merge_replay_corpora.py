from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.acquisition.common import AcquiredComment, AcquisitionProtocolError, write_replay_jsonl
from app.operations.replay import load_replay_corpus


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge private replay corpora with semantic duplicate protection."
    )
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    merged: dict[tuple[str, str], AcquiredComment] = {}
    for path in args.inputs:
        corpus = load_replay_corpus(path)
        for record in corpus.records:
            key = (record.platform.value, record.external_event_key)
            comment = AcquiredComment(
                platform=record.platform,
                comment_id=record.external_comment_id or record.external_event_key,
                source_id=record.external_post_id or "unknown-source",
                thread_id=record.external_event_id,
                text=record.text,
            )
            existing = merged.get(key)
            if existing is not None and existing.replay_object() != comment.replay_object():
                raise AcquisitionProtocolError(
                    "same platform/event key is bound to different replay semantics"
                )
            merged[key] = comment

    result = write_replay_jsonl(args.output, tuple(merged.values()))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
