#!/usr/bin/env python3
"""Fail-closed rollback tests for DayZ maintenance update transactions."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.linux.runtime import maintenance_game_update as maintenance


class DayZMaintenanceRollbackFailureTest(unittest.TestCase):
    def test_failed_activation_rollback_is_not_reported_as_original_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "serverfiles"
            target.mkdir()
            stage = Path(tmp) / "staging"
            stage.mkdir()
            previous = Path(tmp) / "previous"
            previous.mkdir()
            record = {"agent_id": "agent-one", "game_id": "dayz"}
            selection = {"game": "dayz"}

            def detect(*args, **kwargs):
                if args[1] == target and not kwargs.get("force_refresh"):
                    return {"state": "update_available"}
                if args[1] == stage:
                    return {"state": "up_to_date"}
                raise RuntimeError("simulated post-activation detection error")

            patches = [
                patch.object(maintenance, "_context", return_value=("i1", record, {"backup_before_update": False})),
                patch.object(maintenance, "_local_agent_config", return_value={}),
                patch.object(maintenance, "_affected", return_value=[]),
                patch.object(maintenance, "_all_stopped"),
                patch.object(maintenance, "reject_prepared_dayz_transaction"),
                patch.object(maintenance, "_ensure_staging_space"),
                patch.object(maintenance, "_provider_metadata_snapshot", return_value={}),
                patch.object(maintenance, "prepare_staging", return_value=stage),
                patch.object(maintenance, "detect_update", side_effect=detect),
                patch.object(maintenance, "inspect_update_content_preflight", return_value={"status": "ok"}),
                patch.object(maintenance, "reject_unsafe_staged_dayz_content"),
                patch.object(maintenance, "activate", return_value=previous),
                patch.object(maintenance, "rollback", return_value=False),
                patch.object(maintenance, "restore_files"),
                patch.object(maintenance, "cleanup_staging"),
            ]
            with __import__("contextlib").ExitStack() as stack:
                mocks = [stack.enter_context(p) for p in patches]
                with self.assertRaisesRegex(maintenance.MaintenanceGameUpdateError,
                                            "rollback tree is unavailable"):
                    maintenance._prepare_locked(selection, target, lambda _: None)
                mocks[12].assert_called_once_with(target, previous)
                mocks[14].assert_not_called()


if __name__ == "__main__":
    unittest.main()
