"""Print a content-free operational readiness snapshot for an existing SQLite database."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.operations.readiness import OperationalReadinessService
from app.persistence.sqlite import SQLiteDatabase


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        required=True,
        type=Path,
        help="Existing Gheras SQLite database file",
    )
    args = parser.parse_args()

    snapshot = OperationalReadinessService(SQLiteDatabase(args.database)).snapshot()
    payload = asdict(snapshot)
    payload["requires_operator_attention"] = snapshot.requires_operator_attention
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 2 if snapshot.requires_operator_attention else 0


if __name__ == "__main__":
    raise SystemExit(main())
