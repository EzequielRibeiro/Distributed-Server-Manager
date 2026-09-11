#!/usr/bin/env python3
"""SQLite backend using Database Baseline v2."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from backend import DatabaseConnectionError
from baseline_backend_runtime import baseline_status, initialize_baseline, validate_baseline
from backends.sqlite_backend import SQLiteBackend


class _SQLiteSnapshotBaselineView:
    """Minimal Baseline v2 view backed only by a temporary SQLite snapshot."""

    name = "sqlite"

    def __init__(self, database: Path, timeout: int | float):
        self._database = database
        self._timeout = timeout

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self._database,
            timeout=self._timeout,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(path: Path) -> tuple[int, int, str]:
    before = path.stat()
    digest = _sha256(path)
    after = path.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise OSError(f"SQLite source changed while reading: {path}")
    return after.st_size, after.st_mtime_ns, digest


class BaselineSQLiteBackend(SQLiteBackend):
    def _snapshot_source_state(self) -> dict[str, tuple[int, int, str]]:
        database = self.database_path
        wal = database.with_name(database.name + "-wal")
        state: dict[str, tuple[int, int, str]] = {}

        if not database.is_file():
            raise DatabaseConnectionError(
                f"SQLite database does not exist: {database}"
            )

        state[database.name] = _fingerprint(database)
        if wal.is_file():
            state[wal.name] = _fingerprint(wal)
        return state

    def _copy_stable_snapshot(self, destination: Path) -> None:
        """Copy main DB + WAL only when their source bytes stay unchanged."""
        database = self.database_path
        wal = database.with_name(database.name + "-wal")
        journal = database.with_name(database.name + "-journal")
        last_error: Exception | None = None

        for attempt in range(1, 4):
            try:
                if journal.exists():
                    raise OSError(
                        f"active SQLite rollback journal blocks read-only snapshot: {journal}"
                    )

                before = self._snapshot_source_state()
                destination.mkdir(parents=True, exist_ok=True)
                target_database = destination / database.name
                target_wal = destination / wal.name
                shutil.copyfile(database, target_database)

                if wal.name in before:
                    shutil.copyfile(wal, target_wal)
                elif target_wal.exists():
                    target_wal.unlink()

                after = self._snapshot_source_state()
                if before != after:
                    raise OSError("SQLite source changed while snapshot was copied")

                if _sha256(target_database) != before[database.name][2]:
                    raise OSError("SQLite snapshot database digest mismatch")

                if wal.name in before:
                    if not target_wal.is_file():
                        raise OSError("SQLite WAL disappeared from snapshot")
                    if _sha256(target_wal) != before[wal.name][2]:
                        raise OSError("SQLite snapshot WAL digest mismatch")
                elif target_wal.exists():
                    raise OSError("unexpected SQLite WAL in snapshot")

                return
            except (OSError, sqlite3.Error) as exc:
                last_error = exc
                shutil.rmtree(destination, ignore_errors=True)
                if attempt < 3:
                    time.sleep(0.05)

        raise DatabaseConnectionError(
            "could not capture a stable read-only SQLite snapshot: "
            f"{last_error}"
        ) from last_error

    @contextmanager
    def read_only_snapshot(self) -> Iterator[_SQLiteSnapshotBaselineView]:
        """Yield a validation view that never opens the installed DB with SQLite."""
        database = self.database_path
        if not database.is_file():
            raise DatabaseConnectionError(
                f"SQLite database does not exist: {database}"
            )

        with tempfile.TemporaryDirectory(prefix="capivara-sqlite-check-") as temporary:
            snapshot_dir = Path(temporary) / "snapshot"
            self._copy_stable_snapshot(snapshot_dir)
            yield _SQLiteSnapshotBaselineView(
                snapshot_dir / database.name,
                self.config.connect_timeout,
            )

    def health_check_read_only(self) -> Mapping[str, Any]:
        """Validate Baseline v2 without opening the installed SQLite DB."""
        with self.read_only_snapshot() as snapshot:
            return validate_baseline(snapshot)

    def initialize(self) -> Mapping[str, Any]:
        return initialize_baseline(self)

    def migrate(self) -> Mapping[str, Any]:
        # Reconcile first, then return the strict health payload expected by the
        # manager `migrate` command (including `valid`).
        initialize_baseline(self)
        return validate_baseline(self)

    def status(self) -> Mapping[str, Any]:
        return baseline_status(self)

    def health_check(self) -> Mapping[str, Any]:
        return validate_baseline(self)

    def current_schema_version(self) -> int:
        return 0

    def applied_migrations(self) -> Sequence[Mapping[str, Any]]:
        return []


__all__ = ["BaselineSQLiteBackend"]
