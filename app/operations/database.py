"""Safe SQLite integrity inspection and verified backup operations."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.persistence.sqlite import SQLiteDatabase


@dataclass(frozen=True, slots=True)
class DatabaseIntegrityReport:
    """Content-free integrity result for one SQLite database file."""

    integrity_ok: bool
    foreign_key_violations: int

    @property
    def acceptable(self) -> bool:
        return self.integrity_ok and self.foreign_key_violations == 0


@dataclass(frozen=True, slots=True)
class BackupReceipt:
    """Evidence for one newly created and verified SQLite backup."""

    destination: Path
    size_bytes: int
    sha256: str
    created_at: datetime
    integrity: DatabaseIntegrityReport


def inspect_database(database: SQLiteDatabase) -> DatabaseIntegrityReport:
    """Inspect an existing SQLite database without creating or modifying it."""

    with database.connect_readonly() as connection:
        integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
        integrity_ok = bool(integrity_rows) and all(
            str(row[0]).strip().lower() == "ok" for row in integrity_rows
        )
        foreign_key_violations = sum(
            1 for _ in connection.execute("PRAGMA foreign_key_check")
        )
    return DatabaseIntegrityReport(
        integrity_ok=integrity_ok,
        foreign_key_violations=foreign_key_violations,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_verified_backup(
    database: SQLiteDatabase,
    destination: str | Path,
) -> BackupReceipt:
    """Create one consistent backup, refusing implicit overwrite and validating the result."""

    target_path = Path(destination)
    if target_path.exists():
        raise FileExistsError(target_path)
    if not database.path.is_file():
        raise FileNotFoundError(database.path)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with database.connect_readonly() as source, sqlite3.connect(target_path) as target:
            created = True
            source.backup(target)

        integrity = inspect_database(SQLiteDatabase(target_path))
        if not integrity.acceptable:
            raise RuntimeError("backup failed SQLite integrity verification")

        return BackupReceipt(
            destination=target_path,
            size_bytes=target_path.stat().st_size,
            sha256=_sha256_file(target_path),
            created_at=datetime.now(UTC),
            integrity=integrity,
        )
    except Exception:
        if created and target_path.exists():
            target_path.unlink()
        raise
