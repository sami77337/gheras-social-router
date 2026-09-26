from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.operations.replay import load_replay_corpus


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a private replay JSONL corpus and emit content-free "
            "identity metadata."
        )
    )
    parser.add_argument("corpus", type=Path)
    args = parser.parse_args()

    corpus = load_replay_corpus(args.corpus)
    print(json.dumps(asdict(corpus.manifest), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
