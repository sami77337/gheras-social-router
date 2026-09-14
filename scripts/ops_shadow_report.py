"""Print a version-scoped, content-free Shadow evidence report."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.operations.shadow_evidence import ShadowEvidenceService
from app.persistence.sqlite import SQLiteDatabase


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        required=True,
        type=Path,
        help="Existing Gheras SQLite database file",
    )
    parser.add_argument(
        "--evaluator-version",
        required=True,
        help="Exact Shadow evaluator version to report",
    )
    args = parser.parse_args()

    report = ShadowEvidenceService(SQLiteDatabase(args.database)).report(
        args.evaluator_version
    )
    payload = asdict(report)
    payload["first_created_at"] = report.first_created_at.isoformat()
    payload["last_created_at"] = report.last_created_at.isoformat()
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
