from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.acquisition.common import merge_replay_corpora


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge private replay corpora with semantic duplicate protection."
    )
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = merge_replay_corpora(args.inputs, args.output)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
