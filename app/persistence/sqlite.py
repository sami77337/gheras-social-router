"""SQLite connection/bootstrap utilities."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.persistence.operations_schema import OPERATIONS_SCHEMA_SQL
from app.persistence.schema import SCHEMA_SQL


class SQLiteDatabase:
    """Explicit connection factory for a file-backed SQLite V1 database."""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5_000) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms

    @classmethod
    def from_url(cls, database_url: str, *, busy_timeout_ms: int = 5_000) -> SQLiteDatabase:
        """Create a database factory from the configured sqlite URL."""

        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            raise ValueError("only sqlite:/// URLs are supported in V1")
        raw_path = database_url[len(prefix) :]
        if not raw_path:
            raise ValueError("sqlite database path must not be empty")
        return cls(raw_path, busy_timeout_ms=busy_timeout_ms)

    def connect(self) -> sqlite3.Connection:
        """Open one configured SQLite connection with safety pragmas enabled."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def connect_readonly(self) -> sqlite3.Connection:
        """Open an existing database without creating or mutating it."""

        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        uri = f"{self.path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    def initialize(self) -> None:
        """Create the complete idempotent V1 schema, including operational extensions."""

        with self.connect() as connection:
            connection.executescript(SCHEMA_SQL)
            connection.executescript(OPERATIONS_SCHEMA_SQL)
