"""Create one verified, non-overwriting SQLite backup for Gheras."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.operations.database import create_verified_backup
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
        "--destination",
        required=True,
        type=Path,
        help="New backup path; existing files are refused",
    )
    args = parser.parse_args()

    receipt = create_verified_backup(SQLiteDatabase(args.database), args.destination)
    payload = {
        "created_at": receipt.created_at.isoformat(),
        "destination": str(receipt.destination),
        "foreign_key_violations": receipt.integrity.foreign_key_violations,
        "integrity_ok": receipt.integrity.integrity_ok,
        "sha256": receipt.sha256,
        "size_bytes": receipt.size_bytes,
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
