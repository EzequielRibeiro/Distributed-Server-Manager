#!/usr/bin/env python3
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from database import baseline_backend_runtime as runtime
from database.backend import DatabaseMigrationError


class _Connection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _Backend:
    name = "postgresql"

    def __init__(self) -> None:
        self.connection = _Connection()

    def connect(self):
        return self.connection


class BaselineRuntimeReconciledChecksumTest(unittest.TestCase):
    def test_reconciles_marker_when_ledger_is_current_without_replaying_upgrades(self):
        backend = _Backend()
        marker = {
            "name": "capivara-baseline-v2",
            "checksum": "old-checksum",
        }
        current = {
            "ledger_present": True,
            "current_version": 5,
            "latest_version": 5,
            "pending": [],
        }
        baseline = SimpleNamespace(
            name="capivara-baseline-v2",
            checksum="new-checksum",
            sql="",
        )

        with (
            patch.object(runtime, "load_schema_baseline", return_value=baseline),
            patch.object(runtime, "_marker", return_value=marker),
            patch.object(runtime, "_validate_structure", return_value=["schema_baseline"]),
            patch.object(runtime, "upgrade_status", side_effect=[current, current]),
            patch.object(runtime, "apply_pending_upgrades") as apply_pending,
            patch.object(runtime, "_write_marker") as write_marker,
        ):
            result = runtime.initialize_baseline(backend)

        apply_pending.assert_not_called()
        write_marker.assert_called_once_with(
            backend,
            backend.connection,
            name="capivara-baseline-v2",
            checksum="new-checksum",
        )
        self.assertEqual(result["health"], "ok")
        self.assertEqual(result["upgrade_version"], 5)
        self.assertEqual(result["upgrade_latest"], 5)
        self.assertEqual(result["upgraded_now"], [])
        self.assertEqual(backend.connection.commits, 1)

    def test_still_uses_registered_upgrade_path_when_ledger_is_not_current(self):
        backend = _Backend()
        marker = {
            "name": "capivara-baseline-v2",
            "checksum": "old-checksum",
        }
        before = {
            "ledger_present": True,
            "current_version": 4,
            "latest_version": 5,
            "pending": [{"version": 5, "name": "alert_events_note_action"}],
        }
        after = {
            "ledger_present": True,
            "current_version": 5,
            "latest_version": 5,
            "pending": [],
        }
        baseline = SimpleNamespace(
            name="capivara-baseline-v2",
            checksum="new-checksum",
            sql="",
        )

        with (
            patch.object(runtime, "load_schema_baseline", return_value=baseline),
            patch.object(runtime, "_marker", return_value=marker),
            patch.object(runtime, "_validate_structure", return_value=["schema_baseline"]),
            patch.object(runtime, "upgrade_status", side_effect=[before, after]),
            patch.object(runtime, "apply_pending_upgrades", return_value=[5]) as apply_pending,
            patch.object(runtime, "_write_marker") as write_marker,
        ):
            result = runtime.initialize_baseline(backend)

        apply_pending.assert_called_once_with(
            backend,
            backend.connection,
            installed_checksum="old-checksum",
        )
        write_marker.assert_called_once()
        self.assertEqual(result["upgraded_now"], [5])

    def test_checksum_drift_without_reconciled_ledger_or_upgrade_still_fails(self):
        backend = _Backend()
        marker = {
            "name": "capivara-baseline-v2",
            "checksum": "old-checksum",
        }
        before = {
            "ledger_present": False,
            "current_version": 0,
            "latest_version": 5,
            "pending": [{"version": 1, "name": "discord_integration"}],
        }
        baseline = SimpleNamespace(
            name="capivara-baseline-v2",
            checksum="new-checksum",
            sql="",
        )

        with (
            patch.object(runtime, "load_schema_baseline", return_value=baseline),
            patch.object(runtime, "_marker", return_value=marker),
            patch.object(runtime, "upgrade_status", return_value=before),
            patch.object(runtime, "apply_pending_upgrades", return_value=[]),
        ):
            with self.assertRaisesRegex(
                DatabaseMigrationError,
                "checksum differs but no registered upgrade is pending",
            ):
                runtime.initialize_baseline(backend)

        self.assertEqual(backend.connection.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
