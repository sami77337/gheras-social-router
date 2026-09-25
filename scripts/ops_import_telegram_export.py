from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.acquisition.common import write_replay_jsonl
from app.acquisition.telegram_export import load_telegram_desktop_export


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert a private Telegram Desktop HTML export to Gheras replay JSONL."
    )
    parser.add_argument("export", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    batch = load_telegram_desktop_export(args.export)
    replay = write_replay_jsonl(args.output, batch.comments)
    print(
        json.dumps(
            {
                "acquisition": batch.content_free_manifest(),
                "replay": replay,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
