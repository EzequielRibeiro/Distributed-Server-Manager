#!/usr/bin/env python3
"""SQLite backend using Database Baseline v2."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator, Mapping, Sequence

from backend import DatabaseConnectionError
from baseline_backend_runtime import baseline_status, initialize_baseline, validate_baseline
from backends.sqlite_backend import SQLiteBackend


class _ReadOnlySQLiteBaselineView:
    """Minimal Baseline v2 view whose connection cannot mutate SQLite."""

    name = "sqlite"

    def __init__(self, backend: "BaselineSQLiteBackend"):
        self._backend = backend

    def connect(self):
        return self._backend.read_only_connect()


class BaselineSQLiteBackend(SQLiteBackend):
    @contextmanager
    def read_only_connect(self) -> Iterator[sqlite3.Connection]:
        """Open the configured database without creating or writing anything."""

        database = self.database_path
        if not database.is_file():
            raise DatabaseConnectionError(
                f"SQLite database does not exist: {database}"
            )

        try:
            connection = sqlite3.connect(
                f"{database.as_uri()}?mode=ro",
                uri=True,
                timeout=self.config.connect_timeout,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
        except (OSError, sqlite3.Error) as exc:
            raise DatabaseConnectionError(
                f"could not open SQLite database read-only {database}: {exc}"
            ) from exc

        try:
            yield connection
        finally:
            connection.close()

    def _read_only_view(self) -> _ReadOnlySQLiteBaselineView:
        return _ReadOnlySQLiteBaselineView(self)

    def initialize(self) -> Mapping[str, Any]:
        return initialize_baseline(self)

    def migrate(self) -> Mapping[str, Any]:
        # Reconcile first, then return the strict health payload expected by the
        # manager `migrate` command (including `valid`).
        initialize_baseline(self)
        return validate_baseline(self)

    def status(self) -> Mapping[str, Any]:
        return baseline_status(self._read_only_view())

    def health_check(self) -> Mapping[str, Any]:
        return validate_baseline(self._read_only_view())

    def current_schema_version(self) -> int:
        return 0

    def applied_migrations(self) -> Sequence[Mapping[str, Any]]:
        return []


__all__ = ["BaselineSQLiteBackend"]
