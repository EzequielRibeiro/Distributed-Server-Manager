#!/usr/bin/env python3
"""Regression proof for the update preflight SQLite read-only contract."""

from __future__ import annotations

import hashlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"
if str(DATABASE_DIR) not in sys.path:
    sys.path.insert(0, str(DATABASE_DIR))

from backend import DatabaseConfig, DatabaseConnectionError  # noqa: E402
from backends.baseline_sqlite_backend import BaselineSQLiteBackend  # noqa: E402


def snapshot_tree(root: Path) -> dict[str, tuple[str, int, str]]:
    """Return a content-sensitive snapshot without changing the tree."""
    snapshot: dict[str, tuple[str, int, str]] = {}
    if not root.exists():
        return snapshot
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot[relative] = ("dir", path.stat().st_mtime_ns, "")
        elif path.is_file():
            snapshot[relative] = (
                "file",
                path.stat().st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        else:
            snapshot[relative] = ("other", path.lstat().st_mtime_ns, "")
    return snapshot


class UpdatePreflightSQLiteReadOnlyTest(unittest.TestCase):
    def backend(self, database: Path) -> BaselineSQLiteBackend:
        return BaselineSQLiteBackend(
            DatabaseConfig(
                driver="sqlite",
                database=str(database),
                connect_timeout=2,
            )
        )

    def test_missing_database_validation_creates_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "missing-parent"
            database = parent / "capivara.db"
            backend = self.backend(database)

            self.assertFalse(parent.exists())
            with self.assertRaises(DatabaseConnectionError):
                backend.health_check()
            self.assertFalse(parent.exists())
            self.assertFalse(database.exists())

    def test_health_check_preserves_existing_database_bytes_and_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "capivara.db"
            backend = self.backend(database)
            initialized = backend.initialize()
            self.assertEqual("ok", initialized["health"])

            before = snapshot_tree(root)
            result = backend.health_check()
            after = snapshot_tree(root)

            self.assertTrue(result["valid"])
            self.assertEqual(before, after)
            self.assertFalse((root / "capivara.db-journal").exists())

    def test_wal_database_validation_does_not_touch_db_wal_or_shm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "capivara.db"
            backend = self.backend(database)
            backend.initialize()

            writer = sqlite3.connect(database)
            try:
                mode = writer.execute("PRAGMA journal_mode = WAL").fetchone()[0]
                self.assertEqual("wal", str(mode).lower())
                writer.execute(
                    "CREATE TABLE IF NOT EXISTS readonly_probe(id INTEGER PRIMARY KEY)"
                )
                writer.execute("INSERT INTO readonly_probe DEFAULT VALUES")
                writer.commit()

                self.assertTrue((root / "capivara.db-wal").is_file())
                self.assertTrue((root / "capivara.db-shm").is_file())

                before = snapshot_tree(root)
                result = backend.health_check()
                after = snapshot_tree(root)

                self.assertTrue(result["valid"])
                self.assertEqual(before, after)
            finally:
                writer.close()

    def test_rollback_journal_fails_closed_without_source_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "capivara.db"
            backend = self.backend(database)
            backend.initialize()
            journal = root / "capivara.db-journal"
            journal.write_bytes(b"active-journal-sentinel")

            before = snapshot_tree(root)
            with self.assertRaises(DatabaseConnectionError):
                backend.health_check()
            after = snapshot_tree(root)

            self.assertEqual(before, after)

    def test_snapshot_connection_rejects_validation_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "capivara.db"
            backend = self.backend(database)
            backend.initialize()
            before = snapshot_tree(root)

            with backend.read_only_snapshot() as snapshot:
                with snapshot.connect() as connection:
                    with self.assertRaises(sqlite3.OperationalError):
                        connection.execute("CREATE TABLE forbidden_write(id INTEGER)")

            after = snapshot_tree(root)
            self.assertEqual(before, after)

            with sqlite3.connect(database) as connection:
                names = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            self.assertNotIn("forbidden_write", names)


if __name__ == "__main__":
    unittest.main()
